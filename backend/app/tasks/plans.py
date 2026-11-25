"""Edit-plan job: one Claude call, then the free validator."""

import logging
import uuid

from app import storage
from app.celery_app import celery
from app.db import session_scope
from sqlalchemy import func, select

from app.models import MediaStatus, Project, ProjectStatus, Render, Style, StyleStatus
from app.services import ai_usage, plan_ai
from app.services import lessons as LS
from app.services import music
from app.services.prefs import ai_note, enforce, merged_style
from app.services.plan_validate import ClipInfo, PlanError, validate
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
def write_plan(project_id: str, auto_preview: bool = True, request: str | None = None) -> str:
    """The first edit, or (request given) a revision of the current one from the creator's words."""
    with session_scope() as db:
        p = db.get(Project, uuid.UUID(project_id))
        if p is None:
            return "missing"
        style = db.get(Style, p.style_id) if p.style_id else None
        prefs = p.prefs
        profile = merged_style(style.profile if style is not None and style.status == StyleStatus.ready else None, prefs)
        by_alias = aliases(p)
        snapshot, proxies = [], {}
        for alias, c in by_alias.items():
            if c.status != MediaStatus.ready or c.analysis_status != MediaStatus.ready:
                continue
            a = c.analysis or {}
            snapshot.append((alias, str(c.id), c.duration_s or 0, c.contact_sheet_key, a))
            proxies[str(c.id)] = c.proxy_key
        brief = (p.title, p.script, p.language, p.stats)
        user_id = p.user_id
        current = p.plan
        history = list((p.plan_meta or {}).get("history") or [])
        learnt = LS.as_dicts(LS.active(db, user_id))

    if not snapshot:
        return _fail(project_id, "No analysed clips to edit")
    for _, clip_id, _, _, a in snapshot:
        if "reps" not in a and proxies.get(clip_id):
            a["reps"] = _reps_for_old_clip(clip_id, proxies[clip_id])
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
                reps=a.get("reps"),
            )
            for alias, _, duration, sheet_key, a in snapshot
        ]
        lesson = None
        brief_lessons = LS.as_brief(learnt) if learnt else None
        if request and current:
            plan, changes, usage, lesson = plan_ai.revise_plan(inputs, profile, *brief, current, request, ai_note(prefs),
                                                               brief_lessons)
            ai_usage.record(user_id, "edit_revision", usage)
        else:
            plan, usage = plan_ai.write_plan(inputs, profile, *brief, ai_note(prefs), brief_lessons)
            changes = []
            ai_usage.record(user_id, "edit_plan", usage)
        clips = {alias: ClipInfo.of(alias, duration, a) for alias, _, duration, _, a in snapshot}
        if lesson and lesson["rule"] != "none":  # this request's own switch counts right away
            learnt = [*learnt, lesson]
        kept_by_lessons = LS.enforce(plan, learnt)
        enforce(plan, prefs)  # this reel's own choices win over lessons
        plan, warnings, timeline = validate(plan, clips, profile)
        music.assign(plan, project_id)
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
        new_lesson = None
        if lesson:
            ls = LS.learn(db, user_id, lesson["text"], lesson["applies_to"], lesson["rule"], p.id, request)
            new_lesson = {"id": str(ls.id), "text": ls.text, "applies_to": ls.applies_to} if ls else None
        if request:
            history.append({"request": request, "changes": changes, "lesson": new_lesson["text"] if new_lesson else None})
        p.plan_meta = {
            "clip_ids": {alias: cid for alias, cid, *_ in snapshot},
            "timeline": timeline,
            "warnings": warnings,
            "usage": usage,
            "source": "ai",
            "request": request,
            "changes": changes,
            "lesson": new_lesson,  # the app shows "I'll remember: ..." with Undo
            "kept_lessons": kept_by_lessons,
            "history": history[-30:],  # every change request on this reel, oldest first
        }
        p.status, p.error = ProjectStatus.planned, None
        # video first: the creator sees the edit, not a plan - make the quick preview right away
        render_id = start_preview(db, p) if auto_preview else None
    log.info("plan for %s: %.1fs, %d shots, %d warnings", project_id, timeline["total_s"], len(plan.shots), len(warnings))
    if render_id:
        from app.tasks.renders import render_project

        render_project.delay(render_id)
    return "planned"


def _reps_for_old_clip(clip_id: str, proxy_key: str) -> dict | None:
    """Clips analysed before rep counting existed: count once now (~10 s a minute of footage) and keep it."""
    import shutil
    from pathlib import Path

    from app.config import get_settings
    from app.models import Clip
    from app.services import reps

    work = Path(get_settings().work_dir) / "analysis" / "reps" / clip_id
    try:
        found = reps.detect(storage.download_file(proxy_key, work / "proxy.mp4"))
    except Exception:
        log.exception("rep count for old clip %s failed", clip_id)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with session_scope() as db:
        c = db.get(Clip, uuid.UUID(clip_id))
        if c is not None:
            c.analysis = {**(c.analysis or {}), "reps": found}
    return found


def start_preview(db, project: Project) -> str:
    """Queue a quick-preview render of the project's current plan (no AI). Returns the render id;
    the caller sends it to render_project after its transaction commits."""
    version = (db.scalar(select(func.max(Render.version)).where(Render.project_id == project.id)) or 0) + 1
    r = Render(project_id=project.id, version=version, quality="preview", status=MediaStatus.pending, plan=project.plan)
    db.add(r)
    project.status = ProjectStatus.rendering
    db.flush()
    return str(r.id)
