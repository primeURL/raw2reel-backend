"""The edit plan: Claude writes it, the user can edit it, the renderer (Day 6) follows it exactly.

Times:
  shot.in_s / out_s  -> seconds inside the SOURCE clip
  caption / overlay  -> seconds on the FINAL reel timeline
A shot lasts (out_s - in_s) / speed on the timeline; shots play back to back in list order.
"""

from typing import Literal

from pydantic import BaseModel, Field

Position = Literal["upper_third", "middle", "lower_middle"]


class Shot(BaseModel):
    clip: str = Field(description="clip alias, e.g. 'C2'")
    in_s: float = Field(description="start inside the source clip, seconds")
    out_s: float = Field(description="end inside the source clip, seconds")
    speed: float = Field(description="1.0 normal; 0.5-0.95 slow motion; up to 2.0 faster")
    zoom_from: float = Field(description="1.0 = full frame; 1.1-1.8 crops in (a tighter 'second angle')")
    zoom_to: float = Field(description="zoom at the end of the shot; differs from zoom_from for a slow push")
    focus_x: float = Field(description="0-1, horizontal point the zoom centres on (0.5 = middle)")
    focus_y: float = Field(description="0-1, vertical point the zoom centres on")
    keep_audio: bool = Field(description="play the clip's own sound (only if someone speaks or the sound matters)")
    purpose: str = Field(description="why this shot is here, in a few words")


class Caption(BaseModel):
    text: str
    start_s: float = Field(description="seconds on the final reel")
    end_s: float
    position: Position
    highlight: str | None = Field(description="one word/number from text to show in the accent colour, or null")


class StatItem(BaseModel):
    label: str
    value: str


class Overlay(BaseModel):
    type: Literal["stats_card", "title"]
    start_s: float
    end_s: float
    title: str | None = Field(description="heading, e.g. 'DAY 1 · RUN'")
    items: list[StatItem] = Field(description="stats card rows, only from facts the user gave; empty for a title")


EffectType = Literal["punch_in", "slow_push", "spotlight", "grade", "freeze_frame", "flash", "countdown"]
Look = Literal["moody", "bw", "warm", "cool", "pop"]


class Effect(BaseModel):
    """A moment of motion on the final timeline. Effects that zoom or light follow the face."""

    type: EffectType = Field(description=(
        "punch_in: quick zoom onto the face on one key word (0.6-2 s); "
        "slow_push: slow cinematic push in (2-6 s); "
        "spotlight: everything but the person goes dark (1-4 s); "
        "grade: colour look over a stretch (any length, needs look); "
        "freeze_frame: picture freezes with a label and an arrow at the person, sound keeps playing (1-2.5 s); "
        "flash: white flash to accent a cut or a beat (0.15-0.5 s); "
        "countdown: big 3-2-1 above the person (1.5-3 s)"))
    start_s: float = Field(description="seconds on the final reel")
    end_s: float
    text: str | None = Field(default=None, description="freeze_frame label (2-4 words); null for the others")
    look: Look | None = Field(default=None, description="grade only: moody, bw, warm, cool or pop; else null")


class Music(BaseModel):
    enabled: bool
    mood: str
    volume: Literal["low_under_voice", "medium", "music_led"]


class EditPlan(BaseModel):
    title: str
    summary: str = Field(description="2-3 plain sentences describing the edit for the creator")
    shots: list[Shot]
    captions: list[Caption]
    overlays: list[Overlay]
    effects: list[Effect] = Field(default_factory=list, description="a few effects on key moments; [] for a calm edit")
    music: Music
    end_fade_s: float = Field(description="fade to black/silence at the end, 0-1.5 s")


class AIEditPlan(EditPlan):
    """What Claude must write: same plan, but effects is required (it may be [] for a calm edit),
    so the model decides about effects instead of skipping an optional field."""

    effects: list[Effect] = Field(description="a few effects on key moments; [] for a calm edit")
