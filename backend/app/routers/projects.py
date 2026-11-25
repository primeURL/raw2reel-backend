"""Projects (one reel each) and their raw clips.

Clip upload flow (same as references):
  1. POST /projects/{id}/clips/upload-url -> pre-signed R2 PUT URL + clip_id
  2. app PUTs the file straight to R2
  3. POST /projects/{id}/clips/{clip_id}/complete -> worker probes it and makes a thumbnail
"""

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import storage
from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import Clip, MediaStatus, Project, ProjectStatus, Render, Style, StyleStatus, User
from app.routers.styles import get_owned_style
from app.schemas import (
    ALLOWED_VIDEO_TYPES,
    ClipAnalysisOut,
    ClipOrder,
    ClipOut,
    ClipUploadRequest,
    ClipUploadResponse,
    ProjectCreate,
    ProjectOut,
    ProjectSummary,
    ProjectUpdate,
    RenderOut,
    RenderRequest,
    ReviseRequest,
)
from app.services.ai_usage import require_quota
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, PlanError, validate
from app.tasks.analysis import analyze_clip
from app.tasks.clips import process_clip

log = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])

MAX_CLIPS_PER_PROJECT = 12
MAX_CLIP_BYTES = 1024 * 1024 * 1024  # 1 GB (4K phone footage is big)
_EXT_BY_TYPE = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v", "video/webm": ".webm"}
_EDITABLE = {ProjectStatus.draft, ProjectStatus.planned, ProjectStatus.done, ProjectStatus.failed}


# helpers ---------------------------------------------------------------------


def _owned_project(project_id: uuid.UUID, user: User, db: Session, *, with_clips: bool = False) -> Project:
    q = select(Project).where(Project.id == project_id)
    if with_clips:
        q = q.options(selectinload(Project.clips))
    project = db.scalar(q)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def _owned_clip(project: Project, clip_id: uuid.UUID, db: Session) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clip not found")
    return clip


def _require_editable(project: Project) -> None:
    if project.status not in _EDITABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Project is busy ({project.status.value}); try again when it finishes")


def _clip_out(clip: Clip, with_download: bool = False) -> ClipOut:
    out = ClipOut.model_validate(clip)
    if clip.thumbnail_key:
        out.thumbnail_url = storage.presign_get(clip.thumbnail_key)
    if clip.contact_sheet_key:
        out.contact_sheet_url = storage.presign_get(clip.contact_sheet_key)
    t = (clip.analysis or {}).get("transcript") or {}
    if t:
        out.has_speech, out.transcript_text, out.spoken_language = t.get("has_speech"), t.get("text") or None, t.get("language")
    if with_download and clip.status == MediaStatus.ready:
        out.download_url = storage.presign_get(clip.r2_key)
        if clip.proxy_key:
            out.preview_url = storage.presign_get(clip.proxy_key)
    return out


def _summary_fields(clips: list[Clip]) -> dict:
    ready = [c for c in clips if c.status == MediaStatus.ready]
    cover = next((c.thumbnail_key for c in clips if c.thumbnail_key), None)
    return {
        "clip_count": len(clips),
        "total_duration_s": round(sum(c.duration_s or 0 for c in ready), 3),
        "cover_url": storage.presign_get(cover) if cover else None,
        "analysis_ready": bool(clips) and all(
            c.status == MediaStatus.ready and c.analysis_status == MediaStatus.ready for c in clips
        ),
    }


def _project_out(project: Project) -> ProjectOut:
    clips = sorted(project.clips, key=lambda c: c.position)
    out = ProjectOut.model_validate(project, from_attributes=True)
    out.clips = [_clip_out(c, with_download=True) for c in clips]
    meta = project.plan_meta or {}
    out.plan_timeline = meta.get("timeline")
    out.plan_warnings = meta.get("warnings") or []
    out.plan_request = meta.get("request")
    out.plan_changes = meta.get("changes") or []
    out.plan_lesson = meta.get("lesson")
    out.plan_kept_lessons = meta.get("kept_lessons") or []
    out.clip_aliases = {f"C{i}": c.id for i, c in enumerate(clips, start=1)}
    for k, v in _summary_fields(clips).items():
        setattr(out, k, v)
    return out


def _renumber(clips: list[Clip]) -> None:
    for i, c in enumerate(sorted(clips, key=lambda c: c.position)):
        c.position = i


# projects --------------------------------------------------------------------


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProjectOut:
    if body.style_id:
        get_owned_style(body.style_id, user, db)
    project = Project(user_id=user.id, **body.model_dump())
    db.add(project)
    db.commit()
    return _project_out(_owned_project(project.id, user, db, with_clips=True))


@router.get("", response_model=list[ProjectSummary])
def list_projects(
    limit: int = 50, offset: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ProjectSummary]:
    limit = max(1, min(limit, 100))
    projects = db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .options(selectinload(Project.clips))
        .order_by(Project.updated_at.desc())
        .limit(limit)
        .offset(max(offset, 0))
    ).all()
    result = []
    for p in projects:
        s = ProjectSummary.model_validate(p)
        for k, v in _summary_fields(list(p.clips)).items():
            setattr(s, k, v)
        result.append(s)
    return result


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProjectOut:
    return _project_out(_owned_project(project_id, user, db, with_clips=True))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProjectOut:
    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("style_id"):
        get_owned_style(changes["style_id"], user, db)
    for k, v in changes.items():
        setattr(project, k, v)
    db.commit()
    return _project_out(_owned_project(project_id, user, db, with_clips=True))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    project = _owned_project(project_id, user, db)
    try:
        storage.delete_prefix(storage.project_prefix(user.id, project.id))
    except Exception:
        log.exception("could not delete R2 objects for project %s", project.id)
    db.delete(project)
    db.commit()


# clips -----------------------------------------------------------------------


@router.post("/{project_id}/clips/upload-url", response_model=ClipUploadResponse)
def create_clip_upload(
    project_id: uuid.UUID, body: ClipUploadRequest, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ClipUploadResponse:
    project = _owned_project(project_id, user, db)
    _require_editable(project)
    if body.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload an MP4, MOV or WebM video")
    if body.size_bytes and body.size_bytes > MAX_CLIP_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Clips can be at most 1 GB")
    count = db.scalar(select(func.count()).select_from(Clip).where(Clip.project_id == project.id)) or 0
    if count >= MAX_CLIPS_PER_PROJECT:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A reel can have at most {MAX_CLIPS_PER_PROJECT} clips")
    next_pos = db.scalar(select(func.coalesce(func.max(Clip.position) + 1, 0)).where(Clip.project_id == project.id))

    clip = Clip(
        project_id=project.id,
        position=next_pos,
        original_filename=os.path.basename(body.filename)[:300],
        content_type=body.content_type,
        status=MediaStatus.pending,
        r2_key="",
    )
    db.add(clip)
    db.flush()
    clip.r2_key = storage.clip_key(user.id, project.id, clip.id, _EXT_BY_TYPE[body.content_type])
    upload_url = storage.presign_put(clip.r2_key, body.content_type)
    db.commit()
    return ClipUploadResponse(
        clip_id=clip.id,
        upload_url=upload_url,
        key=clip.r2_key,
        headers={"Content-Type": body.content_type},
        expires_in=get_settings().r2_presign_expires_seconds,
    )


@router.post("/{project_id}/clips/{clip_id}/complete", response_model=ClipOut)
def complete_clip_upload(
    project_id: uuid.UUID, clip_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ClipOut:
    project = _owned_project(project_id, user, db)
    clip = _owned_clip(project, clip_id, db)
    if clip.status != MediaStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This clip is not waiting for an upload")
    size = storage.object_size(clip.r2_key)
    if size is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "File not found in storage yet - finish the upload first")
    if size < storage.MIN_VIDEO_BYTES:
        storage.delete_object(clip.r2_key)
        # mark it failed (not left "pending"), so the app shows why and offers Remove
        clip.status = MediaStatus.failed
        clip.error = "The upload didn't contain a video - remove it and add the clip again"
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The upload didn't contain a video ({size} bytes) - please try again")
    clip.status = MediaStatus.processing
    db.commit()
    process_clip.delay(str(clip.id))
    return _clip_out(clip)


@router.get("/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[ClipOut]:
    project = _owned_project(project_id, user, db, with_clips=True)
    return [_clip_out(c, with_download=True) for c in sorted(project.clips, key=lambda c: c.position)]


@router.put("/{project_id}/clips/order", response_model=list[ClipOut])
def reorder_clips(
    project_id: uuid.UUID, body: ClipOrder, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ClipOut]:
    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    by_id = {c.id: c for c in project.clips}
    if len(body.clip_ids) != len(set(body.clip_ids)) or set(body.clip_ids) != set(by_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Send every clip id of this project exactly once")
    for i, cid in enumerate(body.clip_ids):
        by_id[cid].position = i
    db.commit()
    return [_clip_out(by_id[cid]) for cid in body.clip_ids]


@router.delete("/{project_id}/clips/{clip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_clip(
    project_id: uuid.UUID, clip_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    clip = _owned_clip(project, clip_id, db)
    for key in (clip.r2_key, clip.thumbnail_key, clip.proxy_key, clip.contact_sheet_key):
        if key:
            try:
                storage.delete_object(key)
            except Exception:
                log.warning("could not delete %s", key)
    project.clips.remove(clip)
    db.delete(clip)
    _renumber(project.clips)
    db.commit()


@router.get("/{project_id}/clips/{clip_id}/analysis", response_model=ClipAnalysisOut)
def get_clip_analysis(
    project_id: uuid.UUID, clip_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ClipAnalysisOut:
    clip = _owned_clip(_owned_project(project_id, user, db), clip_id, db)
    return ClipAnalysisOut(
        clip_id=clip.id,
        analysis_status=clip.analysis_status,
        analysis=clip.analysis,
        proxy_url=storage.presign_get(clip.proxy_key) if clip.proxy_key else None,
        contact_sheet_url=storage.presign_get(clip.contact_sheet_key) if clip.contact_sheet_key else None,
    )


@router.post("/{project_id}/analyze", response_model=ProjectOut, status_code=status.HTTP_202_ACCEPTED)
def reanalyze_project(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProjectOut:
    """Re-run analysis for every uploaded clip (e.g. after changing the project's language)."""
    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    queued = [c for c in project.clips if c.status == MediaStatus.ready and c.analysis_status != MediaStatus.processing]
    for c in queued:
        c.analysis_status = MediaStatus.pending
    db.commit()
    for c in queued:
        analyze_clip.delay(str(c.id))
    return _project_out(_owned_project(project_id, user, db, with_clips=True))


# edit plan ---------------------------------------------------------------------


@router.post("/{project_id}/plan", response_model=ProjectOut, status_code=status.HTTP_202_ACCEPTED)
def generate_plan(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProjectOut:
    """One AI call: clips + style + script -> edit plan. Replaces the current plan."""
    from app.tasks.plans import write_plan

    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    if not project.clips:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload some clips first")
    if not _summary_fields(list(project.clips))["analysis_ready"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Clips are still being analysed - try again in a moment")
    if project.style_id:
        style = db.get(Style, project.style_id)
        if style is not None and style.status != StyleStatus.ready:
            raise HTTPException(status.HTTP_409_CONFLICT, "Finish setting up the style first (answer its questions)")
    require_quota(db, user.id)
    project.status, project.error = ProjectStatus.analyzing, None
    db.commit()
    write_plan.delay(str(project.id))
    return _project_out(project)


@router.post("/{project_id}/revise", response_model=ProjectOut, status_code=status.HTTP_202_ACCEPTED)
def revise_plan(
    project_id: uuid.UUID, body: ReviseRequest, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProjectOut:
    """One AI call: the creator says what to change ("oats first", "more sounds") -> a revised edit,
    then a new preview is made by itself."""
    from app.tasks.plans import write_plan

    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    if not project.plan:
        raise HTTPException(status.HTTP_409_CONFLICT, "Make the first edit before asking for changes")
    require_quota(db, user.id)
    project.status, project.error = ProjectStatus.analyzing, None
    db.commit()
    write_plan.delay(str(project.id), True, body.request)
    return _project_out(project)


@router.put("/{project_id}/plan", response_model=ProjectOut)
def save_plan(
    project_id: uuid.UUID, body: EditPlan, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProjectOut:
    """The user's own edits to the plan. Checked and auto-fixed by the validator - no AI call."""
    project = _owned_project(project_id, user, db, with_clips=True)
    _require_editable(project)
    clips = sorted(project.clips, key=lambda c: c.position)
    infos = {f"C{i}": ClipInfo.of(f"C{i}", c.duration_s or 0, c.analysis) for i, c in enumerate(clips, start=1) if c.status == MediaStatus.ready}
    style = db.get(Style, project.style_id) if project.style_id else None
    try:
        plan, warnings, timeline = validate(body, infos, style.profile if style is not None else None)
    except PlanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    project.plan = plan.model_dump()
    project.plan_meta = {
        **(project.plan_meta or {}),
        "clip_ids": {f"C{i}": str(c.id) for i, c in enumerate(clips, start=1)},
        "timeline": timeline,
        "warnings": warnings,
        "source": "user",
    }
    project.status, project.error = ProjectStatus.planned, None
    db.commit()
    return _project_out(_owned_project(project_id, user, db, with_clips=True))


# renders -----------------------------------------------------------------------


def _render_out(r: Render) -> RenderOut:
    out = RenderOut.model_validate(r)
    if r.status == MediaStatus.ready and r.r2_key:
        out.video_url = storage.presign_get(r.r2_key)
    if r.thumbnail_key:
        out.thumbnail_url = storage.presign_get(r.thumbnail_key)
    if r.status == MediaStatus.ready and isinstance(r.plan, dict):
        out.checks, out.notes = r.plan.get("_checks"), r.plan.get("_notes")
    return out


@router.post("/{project_id}/render", response_model=RenderOut, status_code=status.HTTP_202_ACCEPTED)
def start_render(
    project_id: uuid.UUID, body: RenderRequest | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> RenderOut:
    """Render the current plan as a new version (v1, v2, ...). No AI call."""
    from app.tasks.renders import render_project

    project = _owned_project(project_id, user, db)
    _require_editable(project)
    if not project.plan:
        raise HTTPException(status.HTTP_409_CONFLICT, "Make an edit plan first")
    version = (db.scalar(select(func.max(Render.version)).where(Render.project_id == project.id)) or 0) + 1
    r = Render(project_id=project.id, version=version, quality=(body or RenderRequest()).quality,
               status=MediaStatus.pending, plan=project.plan)
    db.add(r)
    project.status, project.error = ProjectStatus.rendering, None
    db.commit()
    render_project.delay(str(r.id))
    return _render_out(r)


@router.get("/{project_id}/renders", response_model=list[RenderOut])
def list_renders(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[RenderOut]:
    project = _owned_project(project_id, user, db)
    rows = db.scalars(select(Render).where(Render.project_id == project.id).order_by(Render.version.desc()))
    return [_render_out(r) for r in rows]


@router.delete("/{project_id}/renders/{render_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_render(
    project_id: uuid.UUID, render_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    project = _owned_project(project_id, user, db)
    r = db.get(Render, render_id)
    if r is None or r.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Render not found")
    if r.status in (MediaStatus.pending, MediaStatus.processing):
        raise HTTPException(status.HTTP_409_CONFLICT, "This version is still rendering")
    for key in (r.r2_key, r.thumbnail_key):
        if key:
            try:
                storage.delete_object(key)
            except Exception:
                log.warning("could not delete %s", key)
    db.delete(r)
    db.commit()
