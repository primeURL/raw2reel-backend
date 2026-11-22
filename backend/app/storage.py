"""Cloudflare R2 (S3-compatible) helpers.

Big files never pass through the API: the app uploads/downloads with pre-signed URLs,
and workers read/write R2 directly.
"""

from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings


class StorageNotConfigured(RuntimeError):
    pass


@lru_cache
def _client():
    s = get_settings()
    if not (s.r2_account_id and s.r2_access_key_id and s.r2_secret_access_key):
        _client.cache_clear()
        raise StorageNotConfigured("R2 credentials are not set (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY)")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _bucket() -> str:
    return get_settings().r2_bucket


def presign_put(key: str, content_type: str) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": _bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=get_settings().r2_presign_expires_seconds,
    )


def presign_get(key: str) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=get_settings().r2_presign_expires_seconds,
    )


def upload_file(path: Path, key: str, content_type: str = "video/mp4") -> None:
    _client().upload_file(str(path), _bucket(), key, ExtraArgs={"ContentType": content_type})


def download_file(key: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(_bucket(), key, str(path))
    return path


def read_bytes(key: str) -> bytes:
    return _client().get_object(Bucket=_bucket(), Key=key)["Body"].read()


def object_size(key: str) -> int | None:
    """Size in bytes, or None if the object isn't there."""
    try:
        return int(_client().head_object(Bucket=_bucket(), Key=key)["ContentLength"])
    except ClientError:
        return None


MIN_VIDEO_BYTES = 1024  # anything smaller is an error page or an empty file, not a video


def object_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=_bucket(), Key=key)
        return True
    except ClientError:
        return False


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=_bucket(), Key=key)


# Key layout: everything a user owns lives under users/<user_id>/
def reference_key(user_id, reference_id) -> str:
    return f"users/{user_id}/references/{reference_id}.mp4"


def clip_key(user_id, project_id, clip_id, ext: str) -> str:
    return f"users/{user_id}/projects/{project_id}/raw/{clip_id}{ext}"


def clip_thumb_key(user_id, project_id, clip_id) -> str:
    return f"users/{user_id}/projects/{project_id}/thumbs/{clip_id}.jpg"


def clip_proxy_key(user_id, project_id, clip_id) -> str:
    return f"users/{user_id}/projects/{project_id}/proxy/{clip_id}.mp4"


def clip_sheet_key(user_id, project_id, clip_id) -> str:
    return f"users/{user_id}/projects/{project_id}/sheets/{clip_id}.jpg"


def reference_sheet_key(user_id, reference_id) -> str:
    return f"users/{user_id}/references/{reference_id}-sheet.jpg"


def render_key(user_id, project_id, version: int, quality: str) -> str:
    suffix = "" if quality == "final" else f"-{quality}"
    return f"users/{user_id}/projects/{project_id}/renders/v{version}{suffix}.mp4"


def render_thumb_key(user_id, project_id, version: int, quality: str) -> str:
    suffix = "" if quality == "final" else f"-{quality}"
    return f"users/{user_id}/projects/{project_id}/renders/v{version}{suffix}.jpg"


def project_prefix(user_id, project_id) -> str:
    return f"users/{user_id}/projects/{project_id}/"


def delete_prefix(prefix: str) -> int:
    """Delete every object under a prefix (a whole project). Returns how many were removed."""
    c, removed = _client(), 0
    for page in c.get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            c.delete_objects(Bucket=_bucket(), Delete={"Objects": keys, "Quiet": True})
            removed += len(keys)
    return removed
