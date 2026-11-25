"""Styles: a set of reference reels -> Claude writes a style profile -> 3 questions -> ready.

  draft ──POST /analyze──> analyzing ──> needs_answers ──POST /answers──> analyzing ──> ready
                                    └──> failed (error shown, /analyze again)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import MediaStatus, ReferenceVideo, Style, StyleStatus, User
from app.schemas import StyleAnswers, StyleCreate, StyleOut, StyleRename
from app.services.ai_usage import require_quota

router = APIRouter(prefix="/styles", tags=["styles"])

MIN_REFERENCES = 1  # 3-4 recommended in the app UI


def get_owned_style(style_id: uuid.UUID, user: User, db: Session) -> Style:
    style = db.get(Style, style_id)
    if style is None or style.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Style not found")
    return style


def _refs(style: Style, db: Session) -> list[ReferenceVideo]:
    return list(db.scalars(select(ReferenceVideo).where(ReferenceVideo.style_id == style.id)))


def _out(style: Style, db: Session) -> StyleOut:
    out = StyleOut.model_validate(style)
    refs = _refs(style, db)
    out.reference_count = len(refs)
    out.references_ready = sum(r.analysis_status == MediaStatus.ready for r in refs)
    out.reference_notes = (style.meta or {}).get("reference_notes")
    out.template = (style.meta or {}).get("template")
    return out


@router.post("", response_model=StyleOut, status_code=status.HTTP_201_CREATED)
def create_style(body: StyleCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StyleOut:
    style = Style(user_id=user.id, name=body.name)
    db.add(style)
    db.commit()
    db.refresh(style)
    return _out(style, db)


@router.get("", response_model=list[StyleOut])
def list_styles(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[StyleOut]:
    styles = db.scalars(select(Style).where(Style.user_id == user.id).order_by(Style.created_at.desc()))
    return [_out(s, db) for s in styles]


@router.get("/{style_id}", response_model=StyleOut)
def get_style(style_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StyleOut:
    return _out(get_owned_style(style_id, user, db), db)


@router.patch("/{style_id}", response_model=StyleOut)
def rename_style(
    style_id: uuid.UUID, body: StyleRename, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> StyleOut:
    style = get_owned_style(style_id, user, db)
    style.name = body.name
    db.commit()
    return _out(style, db)


@router.delete("/{style_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_style(style_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """References stay in the library (style_id is cleared); projects keep working without a style."""
    db.delete(get_owned_style(style_id, user, db))
    db.commit()


@router.post("/{style_id}/analyze", response_model=StyleOut, status_code=status.HTTP_202_ACCEPTED)
def analyze_style(style_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StyleOut:
    from app.tasks.styles import analyze_style as job

    style = get_owned_style(style_id, user, db)
    if style.status == StyleStatus.analyzing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already analysing this style")
    refs = _refs(style, db)
    busy = [r for r in refs if r.status in (MediaStatus.pending, MediaStatus.downloading, MediaStatus.processing)
            or r.analysis_status in (MediaStatus.pending, MediaStatus.processing)]
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{len(busy)} reference(s) are still being processed - wait for them to finish")
    if sum(r.analysis_status == MediaStatus.ready for r in refs) < MIN_REFERENCES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add at least one reference reel first (3-4 work best)")
    require_quota(db, user.id)
    style.status, style.error = StyleStatus.analyzing, None
    db.commit()
    job.delay(str(style.id))
    return _out(style, db)


@router.post("/{style_id}/answers", response_model=StyleOut, status_code=status.HTTP_202_ACCEPTED)
def answer_questions(
    style_id: uuid.UUID, body: StyleAnswers, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> StyleOut:
    from app.tasks.styles import apply_style_answers as job

    style = get_owned_style(style_id, user, db)
    if style.status != StyleStatus.needs_answers:
        raise HTTPException(status.HTTP_409_CONFLICT, "This style isn't waiting for answers")
    if not body.answers and not (body.notes or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Answer at least one question or add a note")
    known = {q["id"] for q in style.questions or []}
    unknown = [a.question_id for a in body.answers if a.question_id not in known]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown question id(s): {', '.join(unknown)}")
    require_quota(db, user.id)
    style.answers = [a.model_dump() for a in body.answers]
    if body.notes and body.notes.strip():
        style.answers.append({"question_id": "_notes", "answer": body.notes.strip()})
    style.status, style.error = StyleStatus.analyzing, None
    db.commit()
    job.delay(str(style.id))
    return _out(style, db)


@router.post("/{style_id}/skip-questions", response_model=StyleOut)
def skip_questions(style_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StyleOut:
    """Use the profile as Claude wrote it."""
    style = get_owned_style(style_id, user, db)
    if style.status != StyleStatus.needs_answers:
        raise HTTPException(status.HTTP_409_CONFLICT, "This style isn't waiting for answers")
    style.status = StyleStatus.ready
    db.commit()
    return _out(style, db)
