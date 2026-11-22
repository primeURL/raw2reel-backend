"""Edit-plan job: one Claude call, then the free validator."""

import logging
import uuid

from app import storage
from app.celery_app import celery
from app.db import session_scope
from app.models import MediaStatus, Project, ProjectStatus, Style, StyleStatus
from app.services import ai_usage, plan_ai
from app.services.plan_validate import ClipInfo, PlanError, clip_words, validate
from app.services.style_ai import StyleAIError

log = logging.getLogger(__name__)


def aliases(project: Project) -> dict[str, "object"]:
    """C1, C2... in the project's clip order (short names save tokens and read well in the app)."""
    return {f"C{i}": c for i, c in enumerate(sorted(project.clips, key=lambda c: c.position), start=1)}


def _fail(project_id: str, message: str) -> str:
    with session_scope() as db:
        p = db.get(Project, uuid.UUID(project_id))
        if p is not None:
            p.status, p.error = ProjectStatus.failed, message[:1000]
    return "failed"


@celery.task(name="app.tasks.plans.write_plan")
def write_plan(project_id: str) -> str:
    with session_scope() as db:
        p = db.get(Project, uuid.UUID(project_id))
        if p is None:
            return "missing"
        style = db.get(Style, p.style_id) if p.style_id else None
        profile = style.profile if style is not None and style.status == StyleStatus.ready else None
        by_alias = aliases(p)
        snapshot = []
        for alias, c in by_alias.items():
            if c.status != MediaStatus.ready or c.analysis_status != MediaStatus.ready:
                continue
            a = c.analysis or {}
            snapshot.append((alias, str(c.id), c.duration_s or 0, c.contact_sheet_key, a))
        brief = (p.title, p.script, p.language, p.stats)
        user_id = p.user_id

    if not snapshot:
        return _fail(project_id, "No analysed clips to edit")
    try:
        inputs = [
            plan_ai.ClipInput(
                alias=alias,
                duration_s=duration,
                contact_sheet_jpeg=storage.read_bytes(sheet_key),
                has_speech=bool((a.get("transcript") or {}).get("has_speech")),
                transcript_segments=(a.get("transcript") or {}).get("segments") or [],
                scene_cuts=a.get("scene_cuts") or [],
                silences=a.get("silences") or [],
            )
            for alias, _, duration, sheet_key, a in snapshot
        ]
        plan, usage = plan_ai.write_plan(inputs, profile, *brief)
        ai_usage.record(user_id, "edit_plan", usage)
        clips = {alias: ClipInfo(alias, duration, clip_words(a)) for alias, _, duration, _, a in snapshot}
        plan, warnings, timeline = validate(plan, clips, profile)
    except StyleAIError as exc:
        return _fail(project_id, str(exc))
    except PlanError as exc:
        return _fail(project_id, f"The AI's plan didn't fit your clips: {exc}. Try again.")
    except Exception:
        log.exception("plan writing crashed for %s", project_id)
        return _fail(project_id, "Writing the edit plan failed, please try again")

    with session_scope() as db:
        p = db.get(Project, uuid.UUID(project_id))
        if p is None:
            return "missing"
        p.plan = plan.model_dump()
        p.plan_meta = {
            "clip_ids": {alias: cid for alias, cid, *_ in snapshot},
            "timeline": timeline,
            "warnings": warnings,
            "usage": usage,
            "source": "ai",
        }
        p.status, p.error = ProjectStatus.planned, None
    log.info("plan for %s: %.1fs, %d shots, %d warnings", project_id, timeline["total_s"], len(plan.shots), len(warnings))
    return "planned"
