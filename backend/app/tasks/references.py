"""Reference-reel jobs: Instagram import and checking uploaded files."""

import logging
import shutil
import uuid
from pathlib import Path

from celery.exceptions import Retry

from app import storage
from app.celery_app import celery
from app.config import get_settings
from app.db import session_scope
from app.models import MediaStatus, ReferenceVideo
from app.services import instagram
from app.services.media import probe
from app.tasks.analysis import analyze_reference

log = logging.getLogger(__name__)


def _workdir(reference_id: str) -> Path:
    return Path(get_settings().work_dir) / "references" / reference_id


def _set(reference_id: str, **fields) -> None:
    with session_scope() as db:
        ref = db.get(ReferenceVideo, uuid.UUID(reference_id))
        if ref is None:
            raise LookupError(f"reference {reference_id} not found")
        for k, v in fields.items():
            setattr(ref, k, v)


@celery.task(name="app.tasks.references.import_instagram", bind=True, max_retries=2, default_retry_delay=60)
def import_instagram(self, reference_id: str) -> str:
    with session_scope() as db:
        ref = db.get(ReferenceVideo, uuid.UUID(reference_id))
        if ref is None:
            return "missing"
        url, user_id = ref.source_url, ref.user_id
        ref.status, ref.error = MediaStatus.downloading, None

    work = _workdir(reference_id)
    try:
        result = instagram.download(url, work)
        _set(reference_id, status=MediaStatus.processing)
        info = probe(result.path)
        if info.duration_s > get_settings().instagram_max_duration_seconds:
            _set(reference_id, status=MediaStatus.failed, error="This reel is too long to use as a reference (max 3 minutes).")
            return "failed"
        width, height = info.display_size
        key = storage.reference_key(user_id, reference_id)
        storage.upload_file(result.path, key)
        _set(
            reference_id,
            status=MediaStatus.ready,
            r2_key=key,
            duration_s=info.duration_s,
            width=width,
            height=height,
            meta={"downloader": result.downloader, **{k: v for k, v in result.meta.items() if v is not None}},
            analysis_status=MediaStatus.pending,
        )
        analyze_reference.delay(reference_id)
        return "ready"
    except instagram.DownloadFailed as exc:
        # Instagram blocks are often temporary: retry a couple of times, then give up.
        if self.request.retries < self.max_retries:
            _set(reference_id, status=MediaStatus.pending, error="Retrying download…")
            raise self.retry(exc=exc)
        _set(reference_id, status=MediaStatus.failed, error=str(exc)[:1000])
        return "failed"
    except Retry:
        raise
    except Exception as exc:
        log.exception("instagram import crashed for %s", reference_id)
        _set(reference_id, status=MediaStatus.failed, error=f"Processing error: {exc}"[:1000])
        return "failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)


@celery.task(name="app.tasks.references.process_upload")
def process_upload(reference_id: str) -> str:
    """The app uploaded a reference straight to R2; check it is a real video and read its size."""
    with session_scope() as db:
        ref = db.get(ReferenceVideo, uuid.UUID(reference_id))
        if ref is None or not ref.r2_key:
            return "missing"
        key = ref.r2_key
        ref.status = MediaStatus.processing

    work = _workdir(reference_id)
    try:
        path = storage.download_file(key, work / "upload.mp4")
        info = probe(path)
        if info.duration_s > get_settings().instagram_max_duration_seconds:
            raise ValueError("reference video is too long")
        width, height = info.display_size
        _set(reference_id, status=MediaStatus.ready, duration_s=info.duration_s, width=width, height=height, error=None,
             analysis_status=MediaStatus.pending)
        analyze_reference.delay(reference_id)
        return "ready"
    except Exception as exc:
        log.warning("upload check failed for %s: %s", reference_id, exc)
        msg = str(exc) if isinstance(exc, ValueError) else "the file couldn't be read as a video"
        _set(reference_id, status=MediaStatus.failed, error=f"Not a usable video: {msg}"[:1000])
        return "failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)
