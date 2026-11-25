"""The edit plan: Claude writes it, the user can edit it, the renderer (Day 6) follows it exactly.

Times:
  shot.in_s / out_s  -> seconds inside the SOURCE clip
  caption / overlay  -> seconds on the FINAL reel timeline
A shot lasts (out_s - in_s) / speed on the timeline; shots play back to back in list order.
"""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

Position = Literal["upper_third", "middle", "lower_middle"]

Transition = Literal["cut", "whip", "zoom", "flash"]
TRANSITION_HELP = ("how this shot comes in from the previous one: cut (plain, the default; always for the first "
                   "shot and inside one continuous talking take), whip (fast sideways blur, a jump to a new place "
                   "or step), zoom (quick zoom through the cut, energy or a reveal), flash (white flash on a hard beat)")


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
    transition_in: Transition = Field(default="cut", description=TRANSITION_HELP)


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


EffectType = Literal["punch_in", "slow_push", "spotlight", "grade", "freeze_frame", "flash", "countdown", "backdrop_word",
                     # motion graphics (app/assets/motion/<type>.html)
                     "chat", "counter", "graph", "widgets", "checklist", "progress", "location", "name_card",
                     "follow", "emoji_burst", "poll", "timer", "notification", "price_tag"]
MOTION_HELP = (
    "Motion graphics (1.5-6 s, drawn over the picture; text = their title): "
    "chat: message bubbles pop in one by one (items = messages, 'Me: ...' for your side, 'Name: ...' for others); "
    "counter: a big number counts up (numbers = [from, to] or [to], unit e.g. 'reps', title = label; over exercise footage it counts the real reps, see repeated_movement); "
    "graph: bars rise (numbers = values, items = labels, unit on the last value); "
    "widgets: up to 4 glass cards (items = 'icon|label|value', e.g. '🔥|Calories|120'); "
    "checklist: items tick off one by one (ingredients, steps); "
    "progress: a bar fills (numbers = [current, total], title e.g. 'Day'); "
    "location: a pin drops on a place name (title = place, items[0] = area); "
    "name_card: name and role slide in (title = name, items[0] = role); "
    "follow: a follow button gets tapped (title = @handle); "
    "emoji_burst: emojis float up (items = emojis); "
    "poll: a question with answer bars (title = question, items = answers, numbers = percents); "
    "timer: a clock ring runs down (numbers = [seconds], title = label); "
    "notification: a phone notification drops in (title = sender, items[0] = message); "
    "price_tag: a price sticker spins in (numbers = [price, old price], unit = currency, title e.g. 'SALE')")
MotionPosition = Literal["top", "middle", "bottom"]
Look = Literal["moody", "bw", "warm", "cool", "pop"]


class EffectBase(BaseModel):
    """A moment of motion on the final timeline. Effects that zoom or light follow the face."""

    type: EffectType = Field(description=(
        "punch_in: quick zoom onto the face on one key word (0.6-2 s); "
        "slow_push: slow cinematic push in (2-6 s); "
        "spotlight: everything but the person goes dark (1-4 s); "
        "grade: colour look over a stretch (any length, needs look); "
        "freeze_frame: picture freezes with a label and an arrow at the person, sound keeps playing (1-2.5 s); "
        "flash: white flash to accent a cut or a beat (0.15-0.5 s); "
        "countdown: big 3-2-1 above the person (1.5-3 s); "
        "backdrop_word: one giant word (or two short ones) drops in BEHIND the person, e.g. the topic "
        "or a key result like 'DAY 1' or '5 KM' (1.5-4 s, needs text, only when a person is in frame). " + MOTION_HELP))
    start_s: float = Field(description="seconds on the final reel")
    end_s: float
    text: str | None = Field(default=None, description=(
        "freeze_frame label (2-4 words), backdrop_word word(s) (max 12 letters), or a motion graphic's title; "
        "null for the others"))
    look: Look | None = Field(default=None, description="grade only: moody, bw, warm, cool or pop; else null")
    items: list[str] = Field(default_factory=list, description="motion graphics only (see type); else []")
    numbers: list[float] = Field(default_factory=list, description="motion graphics only (see type); else []")
    unit: str | None = Field(default=None, description="motion graphics only: e.g. 'km', 'reps', '%', '₹'; else null")
    position: MotionPosition | None = Field(default=None, description="motion graphics: top, middle or bottom of the frame; null = its usual spot")
    behind: bool = Field(default=False, description="motion graphics: drawn behind the person (they stay in front)")


class Effect(EffectBase):
    ticks_s: list[float] = Field(default_factory=list, description="set by the app: when each rep finishes (counter)")


def _required(name: str):
    """The same field with no default, so the AI has to write it (null / [] / false when unused).
    Strict structured output gets slow to compile with many optional fields, and the API refuses it."""
    return Field(description=EffectBase.model_fields[name].description)


# The AI writes stats cards and titles as two more effect types (text = heading, items = "label|value"
# rows): a separate overlay list made the plan schema too big for the API's strict mode.
AIEffectType = Literal[EffectType, "stats_card", "title"]
OVERLAY_HELP = ("; stats_card: a card of the creator's numbers (text = heading, items = 'label|value' rows, only "
                "from run_stats; may run past the last shot, the last frame is held under it); title: a big title "
                "card (text = the title, items [])")


class AIEffect(EffectBase):
    type: AIEffectType = Field(description=EffectBase.model_fields["type"].description + OVERLAY_HELP)
    text: str | None = _required("text")
    look: Look | None = _required("look")
    items: list[str] = _required("items")
    numbers: list[float] = _required("numbers")
    unit: str | None = _required("unit")
    position: MotionPosition | None = _required("position")
    behind: bool = _required("behind")


SoundFx = Literal["off", "subtle", "punchy"]
SOUND_FX_HELP = ("sounds under the effects (whoosh on a zoom, a hit when a word lands, ticks on a countdown): "
                 "off for a calm or music-led style, subtle by default, punchy for a high-energy style "
                 "(also a soft pop as captions appear)")


SoundName = Literal["whoosh_fast", "whoosh_soft", "boom", "slam", "shutter", "tick", "pop",
                    "riser", "ding", "click", "swipe", "glitch", "cash"]
BUILT_IN_SOUNDS = ("whoosh_fast", "whoosh_soft", "boom", "slam", "shutter", "tick", "pop")  # app/assets/sfx


class SoundCue(BaseModel):
    """One sound effect, placed by the editor where it helps the story."""

    at_s: float = Field(description="seconds on the final reel where the sound should land")
    sound: SoundName = Field(description=(
        "whoosh_fast: a whip/zoom transition or a punch in; whoosh_soft: a slow push or a gentle scene change; "
        "boom: a big reveal or the spotlight going dark; slam: a word or result landing, a flash; "
        "shutter: a freeze frame or 'snapshot' moment; tick: a countdown or ticking through list items; "
        "pop: a caption or a key word popping on screen; riser: tension building up into a reveal (lands on the reveal); "
        "ding: a tip, an idea or a correct answer; click: a tap, a button, a list item ticking on; swipe: a quick "
        "slide or page change; glitch: a tech/digital moment or a jump; cash: money, a price, a sale"))
    level: Literal["soft", "normal", "loud"] = Field(description="soft under speech, normal by default, loud for the one big moment")
    why: str = Field(description="what it accents, in a few words")


class StoryBeat(BaseModel):
    beat: str = Field(description="one step of the story, in the creator's words, e.g. 'chopping apple and banana'")
    clips: list[str] = Field(description="the clip aliases that show this step, e.g. ['C3', 'C1']")


class Music(BaseModel):
    enabled: bool = Field(description="background music on; off only when the style says none or the creator's audio is the point")
    mood: str = Field(description="one of the library moods given in the brief (music_library), e.g. 'upbeat'")
    volume: Literal["low_under_voice", "medium", "music_led"] = Field(
        description="low_under_voice when someone talks most of the time, music_led when there is little or no speech")


class PlanMusic(Music):
    track: str | None = Field(default=None, description="the library track (chosen by the app, not the AI)")


class EditPlan(BaseModel):
    title: str
    summary: str = Field(description="2-3 plain sentences describing the edit for the creator")
    story: list[StoryBeat] = Field(default_factory=list, description="the story in order, and which clips show each step")
    shots: list[Shot]
    captions: list[Caption]
    overlays: list[Overlay]
    effects: list[Effect] = Field(default_factory=list, description="a few effects on key moments; [] for a calm edit")
    sound_effects: SoundFx = Field(default="subtle", description=SOUND_FX_HELP)
    sounds: list[SoundCue] = Field(default_factory=list, description="the sound design: each sound effect and where it lands")
    music: PlanMusic
    end_fade_s: float = Field(description="fade to black/silence at the end, 0-1.5 s")
    avoid_sounds: SkipJsonSchema[list[str]] = []  # the creator's lessons: sounds never to play (app-side)


class AIShot(Shot):
    transition_in: Transition = Field(description=TRANSITION_HELP)


class AIEditPlan(EditPlan):
    """What Claude must write: same plan, but the creative fields are required (effects and sounds may
    be []), so the model decides about them instead of skipping an optional field. Plans saved
    before these fields existed still load as EditPlan with the defaults."""

    story: list[StoryBeat] = Field(description="the story in order, and which clips show each step")
    shots: list[AIShot]
    effects: list[AIEffect] = Field(description="a few effects on key moments (and any stats card / title); [] for a calm edit")
    overlays: SkipJsonSchema[list[Overlay]] = []  # written as stats_card / title effects, see AIEffectType
    sound_effects: SoundFx = Field(description=SOUND_FX_HELP)
    sounds: list[SoundCue] = Field(description="the sound design: each sound effect and where it lands; [] when sound_effects is off")
    music: Music  # the track itself is picked by the app from the mood
