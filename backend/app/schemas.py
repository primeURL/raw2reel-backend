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


# Creator memory --------------------------------------------------------------


class LessonOut(ORM):
    id: uuid.UUID
    text: str
    applies_to: str
    rule: str | None
    active: bool
    project_id: uuid.UUID | None
    request: str | None
    created_at: datetime


class LessonIn(BaseModel):
    text: str = Field(min_length=3, max_length=200)
    applies_to: str = Field(default="all", max_length=40)


class LessonPatch(BaseModel):
    text: str | None = Field(default=None, min_length=3, max_length=200)
    applies_to: str | None = Field(default=None, max_length=40)
    active: bool | None = None


class LearntLesson(BaseModel):
    id: uuid.UUID
    text: str
    applies_to: str


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
    template: str | None = None  # made from this ready-made template


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


class CaptionPrefs(BaseModel):
    """None = follow the style."""

    enabled: bool | None = None
    animation: Literal["none", "fade", "pop", "slide_up", "typewriter", "karaoke"] | None = None
    look: str | None = Field(default=None, max_length=40)  # a caption look id (app/services/caption_looks.py)
    size: Literal["small", "medium", "large"] | None = None
    position: Literal["upper_third", "middle", "lower_middle"] | None = None
    highlight: bool | None = None
    case: Literal["sentence", "upper"] | None = None


class MusicPrefs(BaseModel):
    """None = the AI decides."""

    enabled: bool | None = None
    track: str | None = Field(default=None, max_length=80)  # a library track id
    volume: Literal["low_under_voice", "medium", "music_led"] | None = None


class Prefs(BaseModel):
    """The creator's own choices for one reel; anything None follows the style."""

    captions: CaptionPrefs = Field(default_factory=CaptionPrefs)
    music: MusicPrefs = Field(default_factory=MusicPrefs)
    sound_effects: Literal["off", "subtle", "punchy"] | None = None
    transitions: Literal["cuts", "smooth", "energetic"] | None = None
    effects: Literal["none", "few", "lots"] | None = None


class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled reel", max_length=200)
    style_id: uuid.UUID | None = None
    script: str | None = Field(default=None, max_length=4000)
    language: Language | None = None
    stats: Stats | None = None
    prefs: Prefs | None = None

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
    prefs: Prefs | None = None

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
    preview_url: str | None = None  # the upright H.264 proxy: what the editor plays (same timing as renders)
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
    prefs: dict | None = None
    plan: dict | None
    plan_timeline: dict | None = None
    plan_warnings: list[str] = []
    plan_request: str | None = None  # what the creator asked for, when the plan is a revision
    plan_changes: list[str] = []  # what the AI changed for that request
    plan_lesson: LearntLesson | None = None  # what the editor learnt from that request (creator memory)
    plan_kept_lessons: list[str] = []  # earlier lessons the app applied to this edit
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


class ReviseRequest(BaseModel):
    request: str = Field(min_length=2, max_length=600)


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
    progress: float | None = None
    stage: str | None = None
    error: str | None
    created_at: datetime
    video_url: str | None = None
    thumbnail_url: str | None = None
    checks: list[dict] | None = None  # quality checks of the finished reel
    notes: list[str] | None = None  # what the renderer fixed on its own (e.g. caption moved off a face)
