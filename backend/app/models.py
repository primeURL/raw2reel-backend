import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    photo_url: Mapped[str | None] = mapped_column(Text)


class StyleStatus(str, enum.Enum):
    draft = "draft"  # collecting references
    analyzing = "analyzing"
    needs_answers = "needs_answers"  # style written, 3 questions waiting
    ready = "ready"
    failed = "failed"


class Style(TimestampMixin, Base):
    """A user's editing style, learned from reference reels (like my-style.md)."""

    __tablename__ = "styles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="My style")
    status: Mapped[StyleStatus] = mapped_column(Enum(StyleStatus, name="style_status"), default=StyleStatus.draft)
    profile: Mapped[dict | None] = mapped_column(JSON)  # structured style guide
    questions: Mapped[list | None] = mapped_column(JSON)
    answers: Mapped[list | None] = mapped_column(JSON)
    meta: Mapped[dict | None] = mapped_column(JSON)  # reference notes, token usage
    error: Mapped[str | None] = mapped_column(Text)

    references: Mapped[list["ReferenceVideo"]] = relationship(back_populates="style", passive_deletes=True)


class ReferenceSource(str, enum.Enum):
    upload = "upload"
    instagram = "instagram"


class MediaStatus(str, enum.Enum):
    pending = "pending"  # waiting for upload / queued
    downloading = "downloading"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class ReferenceVideo(TimestampMixin, Base):
    __tablename__ = "reference_videos"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    style_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("styles.id", ondelete="SET NULL"), index=True)
    source: Mapped[ReferenceSource] = mapped_column(Enum(ReferenceSource, name="reference_source"))
    source_url: Mapped[str | None] = mapped_column(Text)  # normalised Instagram URL
    shortcode: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[MediaStatus] = mapped_column(Enum(MediaStatus, name="media_status"), default=MediaStatus.pending)
    r2_key: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict | None] = mapped_column(JSON)  # caption, author, downloader used...
    error: Mapped[str | None] = mapped_column(Text)
    contact_sheet_key: Mapped[str | None] = mapped_column(Text)
    analysis_status: Mapped[MediaStatus | None] = mapped_column(Enum(MediaStatus, name="media_status"))
    analysis: Mapped[dict | None] = mapped_column(JSON)  # pacing, transcript, loudness

    style: Mapped[Style | None] = relationship(back_populates="references")


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    analyzing = "analyzing"
    planned = "planned"  # edit plan waiting for user approval
    rendering = "rendering"
    done = "done"
    failed = "failed"


class Project(TimestampMixin, Base):
    """One reel being made: raw clips + script -> edit plan -> renders."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    style_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("styles.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), default="Untitled reel")
    script: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))  # en | hi | hinglish
    status: Mapped[ProjectStatus] = mapped_column(Enum(ProjectStatus, name="project_status"), default=ProjectStatus.draft)
    stats: Mapped[dict | None] = mapped_column(JSON)  # facts for a stats card, e.g. {"Distance": "2.06 km"}
    plan: Mapped[dict | None] = mapped_column(JSON)  # current edit plan JSON
    plan_meta: Mapped[dict | None] = mapped_column(JSON)  # clip alias map, timeline, warnings, usage
    prefs: Mapped[dict | None] = mapped_column(JSON)  # the creator's choices: caption look, sounds... (services/prefs.py)
    error: Mapped[str | None] = mapped_column(Text)

    clips: Mapped[list["Clip"]] = relationship(
        back_populates="project", order_by="Clip.position", cascade="all, delete-orphan", passive_deletes=True
    )


class AIUsage(Base):
    """One row per Claude call: who, what for, tokens, estimated cost. Used for the daily limit."""

    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # style_analysis | style_answers | edit_plan
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    estimated_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Render(TimestampMixin, Base):
    """One rendered version of a reel (v1, v2, ...). Never overwritten."""

    __tablename__ = "renders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    quality: Mapped[str] = mapped_column(String(16), default="final")
    status: Mapped[MediaStatus] = mapped_column(Enum(MediaStatus, name="media_status"), default=MediaStatus.pending)
    plan: Mapped[dict] = mapped_column(JSON)  # the exact plan this version was made from
    r2_key: Mapped[str | None] = mapped_column(Text)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    seconds_taken: Mapped[float | None] = mapped_column(Float)
    progress: Mapped[float | None] = mapped_column(Float)  # 0..1 while rendering
    stage: Mapped[str | None] = mapped_column(String(80))  # e.g. "Cutting shot 3 of 6"
    error: Mapped[str | None] = mapped_column(Text)


class Clip(TimestampMixin, Base):
    __tablename__ = "clips"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    r2_key: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[MediaStatus] = mapped_column(Enum(MediaStatus, name="media_status"), default=MediaStatus.pending)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    rotation: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)
    content_type: Mapped[str | None] = mapped_column(String(100))
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    proxy_key: Mapped[str | None] = mapped_column(Text)  # upright 30fps H.264 copy used for rendering
    contact_sheet_key: Mapped[str | None] = mapped_column(Text)
    analysis_status: Mapped[MediaStatus | None] = mapped_column(Enum(MediaStatus, name="media_status"))
    analysis: Mapped[dict | None] = mapped_column(JSON)  # transcript, scenes, silences, loudness
    error: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="clips")


class Lesson(TimestampMixin, Base):
    """Creator memory: something the creator taught the editor by asking for a change (or typed in
    themselves), followed in every later edit. services/lessons.py."""

    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(200))  # e.g. "No pop sounds"
    applies_to: Mapped[str] = mapped_column(String(40), default="all")  # "all" or a kind of reel, e.g. "workout"
    rule: Mapped[str | None] = mapped_column(String(48))  # one the app enforces itself, e.g. "no_sound:pop"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    request: Mapped[str | None] = mapped_column(Text)  # the creator's words it came from
