"""Speak instead of typing: a short voice note becomes text (free - the server's own Whisper, no AI credit)."""

import uuid
from pathlib import Path

from celery.exceptions import TimeoutError as CeleryTimeout
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.auth import current_user
from app.config import get_settings
from app.models import User

router = APIRouter(tags=["voice"])

MAX_BYTES = 15 * 1024 * 1024  # ~3 minutes of phone audio
ALLOWED = {"audio/m4a", "audio/x-m4a", "audio/mp4", "audio/aac", "audio/mpeg", "audio/webm", "audio/ogg", "audio/wav",
           "audio/x-wav", "video/mp4", "video/webm", "application/octet-stream"}


@router.post("/transcribe")
def transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
    user: User = Depends(current_user),
) -> dict:
    from app.tasks.analysis import transcribe_note

    if (audio.content_type or "application/octet-stream") not in ALLOWED:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send an audio recording")
    data = audio.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Keep voice notes under about 3 minutes")
    if len(data) < 512:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That recording is empty - try again")
    if language not in (None, "", "en", "hi", "hinglish"):
        language = None

    # the work dir is shared with the media worker (same volume)
    path = Path(get_settings().work_dir) / "voice" / f"{user.id}-{uuid.uuid4().hex}{Path(audio.filename or 'note.m4a').suffix[:8]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        result = transcribe_note.delay(str(path), language or None).get(timeout=120)
    except CeleryTimeout as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "That took too long - try a shorter note") from exc
    if not result.get("has_speech"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Couldn't hear any speech - try again a bit closer to the mic")
    return result
