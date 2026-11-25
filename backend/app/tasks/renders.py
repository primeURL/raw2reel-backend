"""Render job: plan -> MP4 in R2 as a new version. No AI."""

import logging
import time
import uuid
from pathlib import Path

from app import storage
from app.celery_app import celery
from app.config import get_settings
from app.db import session_scope
from app.models import MediaStatus, Project, ProjectStatus, Render, Style
from app.services import render as R
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, PlanError, validate
from app.services import lessons as LS
from app.services import music
from app.services.prefs import enforce, merged_style

log = logging.getLogger(__name__)


class _ProgressWriter:
    """Saves render progress at most once a second (the app polls every couple of seconds)."""

    def __init__(self, render_id: str):
        self.id, self.last, self.last_stage = uuid.UUID(render_id), 0.0, None

    def __call__(self, fraction: float, stage: str) -> None:
        now = time.monotonic()
        if stage == self.last_stage and now - self.last < 1.0:
            return
        self.last, self.last_stage = now, stage
        try:
            with session_scope() as db:
                r = db.get(Render, self.id)
                if r is not None:
                    r.progress, r.stage = round(max(0.0, min(fraction, 1.0)), 3), stage
        except Exception:  # progress is nice-to-have; never fail a render over it
            log.warning("could not save render progress", exc_info=True)


def _finish(render_id: str, project_id: str, ok: bool, **fields) -> str:
    with session_scope() as db:
        r = db.get(Render, uuid.UUID(render_id))
        if r is not None:
            for k, v in fields.items():
                setattr(r, k, v)
            r.status = MediaStatus.ready if ok else MediaStatus.failed
        p = db.get(Project, uuid.UUID(project_id))
        if p is not None:
            p.status = ProjectStatus.done if ok else ProjectStatus.planned
            p.error = None if ok else fields.get("error")
    return "ready" if ok else "failed"


@celery.task(name="app.tasks.renders.render_project")
def render_project(render_id: str) -> str:
    with session_scope() as db:
        r = db.get(Render, uuid.UUID(render_id))
        if r is None:
            return "missing"
        p = db.get(Project, r.project_id)
        project_id, user_id, version, quality = str(p.id), p.user_id, r.version, r.quality
        style = db.get(Style, p.style_id) if p.style_id else None
        prefs = p.prefs
        learnt = LS.as_dicts(LS.active(db, p.user_id))
        profile = merged_style(style.profile if style is not None else None, prefs)
        clips = sorted(p.clips, key=lambda c: c.position)
        sources = {
            f"C{i}": (c.proxy_key, bool(c.has_audio), c.duration_s or 0, c.analysis)
            for i, c in enumerate(clips, start=1)
            if c.status == MediaStatus.ready and c.proxy_key
        }
        plan_data = r.plan
        r.status = MediaStatus.processing

    work = Path(get_settings().work_dir) / "renders" / render_id
    t0 = time.monotonic()
    try:
        # re-check the plan against today's clips and rules (free) before spending CPU
        plan = EditPlan.model_validate(plan_data)
        LS.enforce(plan, learnt)  # lessons learnt since this edit was written hold too (banned sounds...)
        enforce(plan, prefs)  # choices made after the edit (caption look, sounds off...) need no AI
        plan, warnings, timeline = validate(plan, {a: ClipInfo.of(a, d, an) for a, (_, _, d, an) in sources.items()}, profile)
        music.assign(plan, project_id)  # older plans, or a pick that left the library: choose by mood
        report = _ProgressWriter(render_id)
        report(0.0, "Getting your clips")
        local = {}
        for alias in {s.clip for s in plan.shots}:
            key, has_audio, *_ = sources[alias]
            local[alias] = (storage.download_file(key, work / "src" / f"{alias}.mp4"), has_audio)
        result = R.render(plan, timeline, local, profile, work / "out", quality=quality, progress=report)
        report(0.95, "Saving your reel")

        video_key = storage.render_key(user_id, project_id, version, quality)
        thumb_key = storage.render_thumb_key(user_id, project_id, version, quality)
        storage.upload_file(result.path, video_key)
        storage.upload_file(result.thumbnail, thumb_key, content_type="image/jpeg")
        return _finish(
            render_id, project_id, True, progress=1.0, stage=None,
            r2_key=video_key, thumbnail_key=thumb_key, duration_s=result.duration_s,
            size_bytes=result.path.stat().st_size, seconds_taken=round(time.monotonic() - t0, 1),
            plan={**plan.model_dump(), "_timeline": timeline, "_warnings": warnings + result.notes,
                  "_notes": result.notes, "_checks": result.checks},
        )
    except (PlanError, KeyError) as exc:
        return _finish(render_id, project_id, False, error=f"The plan doesn't match the clips anymore: {exc}")
    except (R.RenderError, R.fx.EffectsError) as exc:
        log.error("render %s failed: %s", render_id, exc)
        return _finish(render_id, project_id, False, error="Rendering failed, please try again")
    except Exception:
        log.exception("render %s crashed", render_id)
        return _finish(render_id, project_id, False, error="Rendering failed, please try again")
    finally:
        R.cleanup(work)
