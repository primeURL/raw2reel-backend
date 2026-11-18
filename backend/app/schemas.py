import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import MediaStatus, ProjectStatus, ReferenceSource, StyleStatus


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: uuid.UUID
    email: str | None
    name: str | None
    photo_url: str | None
    created_at: datetime


# Uploads -------------------------------------------------------------------

ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-m4v", "video/webm"}


class PresignRequest(BaseModel):
    kind: Literal["reference"]  # "clip" arrives with projects on Day 2
    filename: str = Field(max_length=300)
    content_type: str


class PresignResponse(BaseModel):
    upload_url: str
    key: str
    reference_id: uuid.UUID
    headers: dict[str, str]
    expires_in: int


# Styles --------------------------------------------------------------------


class StyleCreate(BaseModel):
    name: str = Field(default="My style", max_length=120)


class StyleOut(ORM):
    id: uuid.UUID
    name: str
    status: StyleStatus
    profile: dict | None
    questions: list | None
    answers: list | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    reference_notes: list[str] | None = None
    reference_count: int = 0
    references_ready: int = 0


class StyleRename(BaseModel):
    name: str = Field(max_length=120, min_length=1)


class StyleAnswer(BaseModel):
    question_id: str = Field(max_length=64)
    answer: str = Field(max_length=300, min_length=1)


class StyleAnswers(BaseModel):
    answers: list[StyleAnswer] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=1000, description="anything else to change, in the user's words")


# References ----------------------------------------------------------------


class InstagramImport(BaseModel):
    url: str = Field(max_length=500, examples=["https://www.instagram.com/reel/ABC123xyz/"])
    style_id: uuid.UUID | None = None


class UploadComplete(BaseModel):
    style_id: uuid.UUID | None = None


class ReferenceOut(ORM):
    id: uuid.UUID
    style_id: uuid.UUID | None
    source: ReferenceSource
    source_url: str | None
    shortcode: str | None
    status: MediaStatus
    duration_s: float | None
    width: int | None
    height: int | None
    error: str | None
    created_at: datetime
    download_url: str | None = None
    analysis_status: MediaStatus | None = None
    contact_sheet_url: str | None = None
    pacing: dict | None = None
    transcript_text: str | None = None


# Projects & clips ------------------------------------------------------------

Language = Literal["en", "hi", "hinglish"]


Stats = dict[str, str]  # label -> value, e.g. {"Distance": "2.06 km", "Pace": "7'20\" /km"}


def _check_stats(v: Stats | None) -> Stats | None:
    if v is None:
        return v
    if len(v) > 8 or any(len(k) > 40 or len(x) > 40 for k, x in v.items()):
        raise ValueError("at most 8 stats, each label/value up to 40 characters")
    return v


class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled reel", max_length=200)
    style_id: uuid.UUID | None = None
    script: str | None = Field(default=None, max_length=4000)
    language: Language | None = None
    stats: Stats | None = None

    @field_validator("stats")
    @classmethod
    def _stats(cls, v: Stats | None) -> Stats | None:
        return _check_stats(v)


class ProjectUpdate(BaseModel):
    """Only fields that are sent are changed."""

    title: str | None = Field(default=None, max_length=200)
    style_id: uuid.UUID | None = None
    script: str | None = Field(default=None, max_length=4000)
    language: Language | None = None
    stats: Stats | None = None

    @field_validator("stats")
    @classmethod
    def _stats(cls, v: Stats | None) -> Stats | None:
        return _check_stats(v)


class ClipOut(ORM):
    id: uuid.UUID
    position: int
    original_filename: str | None
    status: MediaStatus
    duration_s: float | None
    width: int | None
    height: int | None
    rotation: int | None
    fps: float | None
    has_audio: bool | None
    error: str | None
    created_at: datetime
    thumbnail_url: str | None = None
    download_url: str | None = None
    analysis_status: MediaStatus | None = None
    contact_sheet_url: str | None = None
    has_speech: bool | None = None
    transcript_text: str | None = None
    spoken_language: str | None = None


class ProjectSummary(ORM):
    id: uuid.UUID
    title: str
    style_id: uuid.UUID | None
    status: ProjectStatus
    language: str | None
    created_at: datetime
    updated_at: datetime
    clip_count: int = 0
    total_duration_s: float = 0.0
    cover_url: str | None = None
    analysis_ready: bool = False  # every clip uploaded and analysed -> ready for an edit plan


class ProjectOut(ProjectSummary):
    script: str | None
    stats: dict | None
    plan: dict | None
    plan_timeline: dict | None = None
    plan_warnings: list[str] = []
    clip_aliases: dict[str, uuid.UUID] = {}
    error: str | None
    clips: list[ClipOut] = []


class ClipUploadRequest(BaseModel):
    filename: str = Field(max_length=300)
    content_type: str
    size_bytes: int | None = Field(default=None, ge=1)


class ClipUploadResponse(BaseModel):
    clip_id: uuid.UUID
    upload_url: str
    key: str
    headers: dict[str, str]
    expires_in: int


class ClipOrder(BaseModel):
    clip_ids: list[uuid.UUID] = Field(min_length=1)


class ClipAnalysisOut(BaseModel):
    clip_id: uuid.UUID
    analysis_status: MediaStatus | None
    analysis: dict | None
    proxy_url: str | None = None
    contact_sheet_url: str | None = None


class RenderRequest(BaseModel):
    quality: Literal["preview", "final"] = "final"


class RenderOut(ORM):
    id: uuid.UUID
    version: int
    quality: str
    status: MediaStatus
    duration_s: float | None
    size_bytes: int | None
    seconds_taken: float | None
    error: str | None
    created_at: datetime
    video_url: str | None = None
    thumbnail_url: str | None = None
