"""Raw clip jobs. Day 2: check the upload, read its specs, make a thumbnail.

Transcription, scene detection and contact sheets join this pipeline on Day 3.
"""

import logging
import shutil
import uuid
from pathlib import Path

from celery.exceptions import Retry

from app import storage
from app.celery_app import celery
from app.config import get_settings
from app.db import session_scope
from app.models import Clip, MediaStatus, Project
from app.services.media import probe, thumbnail

log = logging.getLogger(__name__)

MAX_CLIP_SECONDS = 5 * 60


@celery.task(name="app.tasks.clips.process_clip", bind=True, max_retries=2, default_retry_delay=30)
def process_clip(self, clip_id: str) -> str:
    with session_scope() as db:
        clip = db.get(Clip, uuid.UUID(clip_id))
        if clip is None:
            return "missing"
        project = db.get(Project, clip.project_id)
        key, user_id, project_id = clip.r2_key, project.user_id, project.id

    work = Path(get_settings().work_dir) / "clips" / clip_id
    try:
        try:
            src = storage.download_file(key, work / f"src{Path(key).suffix}")
        except Exception as exc:  # network blip talking to R2: retry
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            raise

        try:
            info = probe(src)
        except Exception:
            return _fail(clip_id, "This file couldn't be read as a video")
        if info.duration_s <= 0.2:
            return _fail(clip_id, "This clip is empty or too short")
        if info.duration_s > MAX_CLIP_SECONDS:
            return _fail(clip_id, "Clips can be at most 5 minutes long")

        thumb = thumbnail(src, work / "thumb.jpg", at_s=min(1.0, info.duration_s / 2))
        thumb_key = storage.clip_thumb_key(user_id, project_id, clip_id)
        storage.upload_file(thumb, thumb_key, content_type="image/jpeg")

        width, height = info.display_size
        with session_scope() as db:
            clip = db.get(Clip, uuid.UUID(clip_id))
            if clip is None:  # deleted while we worked
                storage.delete_object(thumb_key)
                return "missing"
            clip.status = MediaStatus.ready
            clip.duration_s = round(info.duration_s, 3)
            clip.width, clip.height = width, height
            clip.rotation = info.rotation
            clip.fps = info.fps
            clip.has_audio = info.has_audio
            clip.thumbnail_key = thumb_key
            clip.error = None
            clip.analysis_status = MediaStatus.pending
        from app.tasks.analysis import analyze_clip

        analyze_clip.delay(clip_id)
        return "ready"
    except Retry:
        raise  # let Celery schedule the retry
    except Exception:
        log.exception("clip processing failed for %s", clip_id)
        return _fail(clip_id, "Processing failed, please try uploading again")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _fail(clip_id: str, message: str) -> str:
    with session_scope() as db:
        clip = db.get(Clip, uuid.UUID(clip_id))
        if clip is not None:
            clip.status = MediaStatus.failed
            clip.error = message
    return "failed"
