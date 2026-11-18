"""Analysis jobs. Run automatically after a clip or reference is ready."""

import logging
import shutil
import statistics
import time
import uuid
from pathlib import Path

from app import storage
from app.celery_app import celery
from app.config import get_settings
from app.db import session_scope
from app.models import Clip, MediaStatus, Project, ReferenceVideo
from app.services import analysis as A

log = logging.getLogger(__name__)


class _Timer:
    def __init__(self):
        self.t, self.laps = time.monotonic(), {}

    def lap(self, name: str) -> None:
        now = time.monotonic()
        self.laps[name] = round(now - self.t, 1)
        self.t = now


def _work(kind: str, id_: str) -> Path:
    return Path(get_settings().work_dir) / "analysis" / kind / id_


# clips -----------------------------------------------------------------------


@celery.task(name="app.tasks.analysis.analyze_clip")
def analyze_clip(clip_id: str) -> str:
    with session_scope() as db:
        clip = db.get(Clip, uuid.UUID(clip_id))
        if clip is None or clip.status != MediaStatus.ready:
            return "skipped"
        project = db.get(Project, clip.project_id)
        key, duration = clip.r2_key, clip.duration_s or 0
        user_id, project_id, language = project.user_id, project.id, project.language
        clip.analysis_status = MediaStatus.processing

    work = _work("clips", clip_id)
    t0 = time.monotonic()
    try:
        timer = _Timer()
        src = storage.download_file(key, work / f"src{Path(key).suffix}")
        timer.lap("download")

        proxy = A.make_proxy(src, work / "proxy.mp4")
        timer.lap("proxy")
        proxy_key = storage.clip_proxy_key(user_id, project_id, clip_id)
        storage.upload_file(proxy, proxy_key)
        timer.lap("upload_proxy")

        sheet_meta = A.contact_sheet(proxy, work / "sheet.jpg", duration)
        sheet_key = storage.clip_sheet_key(user_id, project_id, clip_id)
        storage.upload_file(work / "sheet.jpg", sheet_key, content_type="image/jpeg")
        timer.lap("contact_sheet")

        result = {
            "scene_cuts": A.scene_cuts(proxy),
            "silences": A.silences(proxy),
            "loudness_lufs": A.loudness_lufs(proxy),
            "contact_sheet": sheet_meta,
        }
        timer.lap("scenes_silence_loudness")
        result["transcript"] = A.transcribe(proxy, language)
        timer.lap("transcribe")
        result["seconds_taken"] = round(time.monotonic() - t0, 1)
        result["timings"] = timer.laps

        with session_scope() as db:
            clip = db.get(Clip, uuid.UUID(clip_id))
            if clip is None:
                return "missing"
            clip.proxy_key, clip.contact_sheet_key = proxy_key, sheet_key
            clip.analysis, clip.analysis_status = result, MediaStatus.ready
        log.info("clip %s analysed in %ss", clip_id, result["seconds_taken"])
        return "ready"
    except Exception as exc:
        log.exception("clip analysis failed for %s", clip_id)
        with session_scope() as db:
            clip = db.get(Clip, uuid.UUID(clip_id))
            if clip is not None:
                clip.analysis_status = MediaStatus.failed
                clip.analysis = {"error": str(exc)[:500]}
        return "failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)


# references --------------------------------------------------------------------


def pacing(cuts: list[float], duration: float) -> dict:
    """Shot lengths from scene cuts - the 'how fast are the cuts' part of a style."""
    edges = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    shots = [round(b - a, 2) for a, b in zip(edges, edges[1:]) if b - a > 0.05]
    return {
        "shot_count": len(shots),
        "shot_lengths": shots,
        "avg_shot_s": round(statistics.mean(shots), 2) if shots else None,
        "median_shot_s": round(statistics.median(shots), 2) if shots else None,
        "cuts_per_10s": round(10 * max(len(shots) - 1, 0) / duration, 2) if duration else None,
    }


@celery.task(name="app.tasks.analysis.analyze_reference")
def analyze_reference(reference_id: str) -> str:
    with session_scope() as db:
        ref = db.get(ReferenceVideo, uuid.UUID(reference_id))
        if ref is None or ref.status != MediaStatus.ready or not ref.r2_key:
            return "skipped"
        key, duration, user_id = ref.r2_key, ref.duration_s or 0, ref.user_id
        ref.analysis_status = MediaStatus.processing

    work = _work("references", reference_id)
    t0 = time.monotonic()
    try:
        src = storage.download_file(key, work / "src.mp4")
        sheet_meta = A.contact_sheet(src, work / "sheet.jpg", duration, frames=16, cols=8)
        sheet_key = storage.reference_sheet_key(user_id, reference_id)
        storage.upload_file(work / "sheet.jpg", sheet_key, content_type="image/jpeg")

        cuts = A.scene_cuts(src)
        transcript = A.transcribe(src, None)
        result = {
            "scene_cuts": cuts,
            "pacing": pacing(cuts, duration),
            "loudness_lufs": A.loudness_lufs(src),
            "contact_sheet": sheet_meta,
            "transcript": transcript,
            "seconds_taken": round(time.monotonic() - t0, 1),
        }
        with session_scope() as db:
            ref = db.get(ReferenceVideo, uuid.UUID(reference_id))
            if ref is None:
                return "missing"
            ref.contact_sheet_key, ref.analysis, ref.analysis_status = sheet_key, result, MediaStatus.ready
        return "ready"
    except Exception as exc:
        log.exception("reference analysis failed for %s", reference_id)
        with session_scope() as db:
            ref = db.get(ReferenceVideo, uuid.UUID(reference_id))
            if ref is not None:
                ref.analysis_status = MediaStatus.failed
                ref.analysis = {"error": str(exc)[:500]}
        return "failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)
