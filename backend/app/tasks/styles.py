"""Style jobs: learn a style from its references, then fold in the user's answers."""

import logging
import uuid

from sqlalchemy import select

from app import storage
from app.celery_app import celery
from app.db import session_scope
from app.models import MediaStatus, ReferenceVideo, Style, StyleStatus
from app.services import ai_usage, style_ai

log = logging.getLogger(__name__)


def _fail(style_id: str, message: str) -> str:
    with session_scope() as db:
        style = db.get(Style, uuid.UUID(style_id))
        if style is not None:
            style.status, style.error = StyleStatus.failed, message[:1000]
    return "failed"


@celery.task(name="app.tasks.styles.analyze_style")
def analyze_style(style_id: str) -> str:
    with session_scope() as db:
        style = db.get(Style, uuid.UUID(style_id))
        if style is None:
            return "missing"
        refs = db.scalars(
            select(ReferenceVideo)
            .where(ReferenceVideo.style_id == style.id, ReferenceVideo.analysis_status == MediaStatus.ready)
            .order_by(ReferenceVideo.created_at)
        ).all()
        name, user_id = style.name, style.user_id
        snapshot = [
            (r.id, r.duration_s or 0, r.contact_sheet_key, r.analysis or {}, (r.meta or {}).get("caption"))
            for r in refs
        ]

    if not snapshot:
        return _fail(style_id, "No analysed reference reels yet")
    try:
        inputs = []
        for i, (rid, duration, sheet_key, analysis, caption) in enumerate(snapshot, start=1):
            transcript = analysis.get("transcript") or {}
            inputs.append(
                style_ai.ReferenceInput(
                    index=i,
                    duration_s=duration,
                    contact_sheet_jpeg=storage.read_bytes(sheet_key),
                    pacing=analysis.get("pacing"),
                    loudness_lufs=analysis.get("loudness_lufs"),
                    transcript=transcript.get("text") or "",
                    spoken_language=transcript.get("language"),
                    ig_caption=caption,
                )
            )
        result, usage = style_ai.analyze_references(inputs, name)
        ai_usage.record(user_id, "style_analysis", usage)
    except style_ai.StyleAIError as exc:
        return _fail(style_id, str(exc))
    except Exception:
        log.exception("style analysis crashed for %s", style_id)
        return _fail(style_id, "Style analysis failed, please try again")

    with session_scope() as db:
        style = db.get(Style, uuid.UUID(style_id))
        if style is None:
            return "missing"
        style.profile = result.profile.model_dump()
        style.questions = [q.model_dump() for q in result.questions[:3]]
        style.answers = None
        style.meta = {
            "reference_ids": [str(r[0]) for r in snapshot],
            "reference_notes": result.reference_notes,
            "analysis_usage": usage,
        }
        style.status, style.error = StyleStatus.needs_answers, None
    return "needs_answers"


@celery.task(name="app.tasks.styles.apply_style_answers")
def apply_style_answers(style_id: str) -> str:
    with session_scope() as db:
        style = db.get(Style, uuid.UUID(style_id))
        if style is None:
            return "missing"
        profile, questions, answers = style.profile, style.questions or [], style.answers or []
        user_id = style.user_id
    try:
        updated, usage = style_ai.apply_answers(profile, questions, answers)
        ai_usage.record(user_id, "style_answers", usage)
    except style_ai.StyleAIError as exc:
        return _fail(style_id, str(exc))
    except Exception:
        log.exception("applying answers crashed for %s", style_id)
        return _fail(style_id, "Updating the style failed, please try again")
    with session_scope() as db:
        style = db.get(Style, uuid.UUID(style_id))
        if style is None:
            return "missing"
        style.profile = updated.model_dump()
        style.meta = {**(style.meta or {}), "answers_usage": usage}
        style.status, style.error = StyleStatus.ready, None
    return "ready"
