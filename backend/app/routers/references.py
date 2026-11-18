"""Reference reels: import from an Instagram link, or upload a file straight to R2."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import MediaStatus, ReferenceSource, ReferenceVideo, User
from app.routers.styles import get_owned_style
from app.schemas import (
    ALLOWED_VIDEO_TYPES,
    InstagramImport,
    PresignRequest,
    PresignResponse,
    ReferenceOut,
    UploadComplete,
)
from app.services.instagram import InvalidInstagramUrl, parse_instagram_url
from app.tasks.references import import_instagram, process_upload

router = APIRouter(prefix="/references", tags=["references"])

MAX_REFERENCES_PER_STYLE = 6


def _owned(reference_id: uuid.UUID, user: User, db: Session) -> ReferenceVideo:
    ref = db.get(ReferenceVideo, reference_id)
    if ref is None or ref.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference not found")
    return ref


def _out(ref: ReferenceVideo) -> ReferenceOut:
    out = ReferenceOut.model_validate(ref)
    if ref.status == MediaStatus.ready and ref.r2_key:
        out.download_url = storage.presign_get(ref.r2_key)
    if ref.contact_sheet_key:
        out.contact_sheet_url = storage.presign_get(ref.contact_sheet_key)
    a = ref.analysis or {}
    out.pacing = a.get("pacing")
    out.transcript_text = (a.get("transcript") or {}).get("text") or None
    return out


def _check_style_room(style_id: uuid.UUID | None, user: User, db: Session) -> None:
    if style_id is None:
        return
    get_owned_style(style_id, user, db)
    count = len(list(db.scalars(select(ReferenceVideo.id).where(ReferenceVideo.style_id == style_id))))
    if count >= MAX_REFERENCES_PER_STYLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A style can have at most {MAX_REFERENCES_PER_STYLE} references")


@router.post("/instagram", response_model=ReferenceOut, status_code=status.HTTP_202_ACCEPTED)
def import_from_instagram(
    body: InstagramImport, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ReferenceOut:
    try:
        parsed = parse_instagram_url(body.url)
    except InvalidInstagramUrl as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    _check_style_room(body.style_id, user, db)

    ref = ReferenceVideo(
        user_id=user.id,
        style_id=body.style_id,
        source=ReferenceSource.instagram,
        source_url=parsed.canonical_url,
        shortcode=parsed.shortcode,
        status=MediaStatus.pending,
    )
    db.add(ref)
    db.commit()
    db.refresh(ref)
    import_instagram.delay(str(ref.id))
    return _out(ref)


@router.post("/upload-url", response_model=PresignResponse)
def create_upload_url(
    body: PresignRequest, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> PresignResponse:
    if body.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload an MP4, MOV or WebM video")
    ref = ReferenceVideo(user_id=user.id, source=ReferenceSource.upload, status=MediaStatus.pending)
    db.add(ref)
    db.flush()
    ref.r2_key = storage.reference_key(user.id, ref.id)
    ref.meta = {"original_filename": body.filename}
    db.commit()
    return PresignResponse(
        upload_url=storage.presign_put(ref.r2_key, body.content_type),
        key=ref.r2_key,
        reference_id=ref.id,
        headers={"Content-Type": body.content_type},
        expires_in=get_settings().r2_presign_expires_seconds,
    )


@router.post("/{reference_id}/complete", response_model=ReferenceOut)
def complete_upload(
    reference_id: uuid.UUID, body: UploadComplete, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ReferenceOut:
    ref = _owned(reference_id, user, db)
    if ref.source != ReferenceSource.upload or ref.status != MediaStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This reference is not waiting for an upload")
    if not storage.object_exists(ref.r2_key):
        raise HTTPException(status.HTTP_409_CONFLICT, "File not found in storage yet - finish the upload first")
    _check_style_room(body.style_id, user, db)
    ref.style_id = body.style_id
    ref.status = MediaStatus.processing
    db.commit()
    process_upload.delay(str(ref.id))
    return _out(ref)


@router.get("", response_model=list[ReferenceOut])
def list_references(
    style_id: uuid.UUID | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ReferenceOut]:
    q = select(ReferenceVideo).where(ReferenceVideo.user_id == user.id)
    if style_id:
        q = q.where(ReferenceVideo.style_id == style_id)
    return [_out(r) for r in db.scalars(q.order_by(ReferenceVideo.created_at.desc()))]


@router.get("/{reference_id}", response_model=ReferenceOut)
def get_reference(reference_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ReferenceOut:
    return _out(_owned(reference_id, user, db))


@router.post("/{reference_id}/retry", response_model=ReferenceOut, status_code=status.HTTP_202_ACCEPTED)
def retry_import(reference_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ReferenceOut:
    ref = _owned(reference_id, user, db)
    if ref.source != ReferenceSource.instagram or ref.status != MediaStatus.failed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed Instagram imports can be retried")
    ref.status, ref.error = MediaStatus.pending, None
    db.commit()
    import_instagram.delay(str(ref.id))
    return _out(ref)


@router.delete("/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(reference_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    ref = _owned(reference_id, user, db)
    for key in (ref.r2_key, ref.contact_sheet_key):
        if key:
            try:
                storage.delete_object(key)
            except Exception:
                pass  # the row goes anyway; an orphaned object can be swept later
    db.delete(ref)
    db.commit()
