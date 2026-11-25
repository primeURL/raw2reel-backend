"""The style profile: what Claude learns from reference reels, and what the edit planner
(Day 5) and renderer (Day 6) obey. Mirrors the my-style.md written by hand for the Day 1 reel,
but as fields a program can follow.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.services.caption_looks import LOOK_IDS, help_text

CaptionLookId = Literal[LOOK_IDS]  # type: ignore[valid-type]


class Pacing(BaseModel):
    reel_type: Literal["cinematic", "talking_tips", "mixed"] = Field(
        description="cinematic = few long shots + music + short text; talking_tips = someone speaking to camera"
    )
    target_length_s: list[int] = Field(description="[min, max] total reel length in seconds, e.g. [8, 20]")
    shot_length_s: list[float] = Field(description="[min, max] typical shot length in seconds")
    cut_on_beat: bool
    dead_air: Literal["cut_tight", "keep_natural_pauses", "keep_all"] = Field(
        description="how silences/pauses inside speech are handled"
    )
    notes: str


class Captions(BaseModel):
    enabled: bool
    mode: Literal["word_by_word", "phrase", "full_line"] = Field(description="how much text is on screen at once")
    max_words_on_screen: int
    size: Literal["small", "medium", "large"]
    weight: Literal["regular", "medium", "bold", "heavy"]
    case: Literal["sentence", "lower", "upper", "as_spoken"]
    position: Literal["upper_third", "middle", "lower_middle"] = Field(
        description="never in the bottom 15% (app buttons)"
    )
    animation: Literal["none", "fade", "pop", "slide_up", "typewriter", "karaoke"] = Field(
        description="karaoke = the whole line shows and the highlight moves word by word as it is spoken")
    look: CaptionLookId | None = Field(default=None, description=(
        "the ready-made caption design closest to the references' captions (font feel, outline, boxes, "
        "how the key word is marked): " + help_text()))
    keyword_highlight: bool = Field(description="emphasise numbers / key words with the accent colour")
    text_color: str = Field(description="hex, e.g. #FFFFFF")
    font_feel: str = Field(description="describe the type feel, e.g. 'clean rounded sans', 'elegant serif' - never a copied brand font")
    language_script: Literal["roman", "devanagari", "as_spoken"] = Field(
        description="for Hindi/Hinglish speech: write Hindi words in Roman letters or Devanagari"
    )


class Hook(BaseModel):
    style: Literal["question_title", "bold_claim_title", "strongest_shot", "result_first", "face_and_line"]
    title_card: bool = Field(description="a short title in the first ~2 s")
    notes: str


class Look(BaseModel):
    grade: Literal["natural", "warm", "cool", "black_and_white", "high_contrast", "muted_film"]
    letterbox: bool
    zooms: Literal["none", "slow_push", "punch_in_on_emphasis"]
    transitions: Literal["hard_cuts", "dissolves", "whip", "mixed"]
    overlays: list[str] = Field(description="graphic ideas, e.g. 'run stats card', 'progress bar'")
    accent_color: str = Field(description="hex accent colour for highlights and cards")


class Sound(BaseModel):
    music: Literal["none", "under_voice", "music_led"]
    music_mood: str
    keep_original_audio: bool = Field(description="keep the camera's own sound (voice, ambience)")
    sound_effects: Literal["none", "subtle", "frequent"]


class Ending(BaseModel):
    style: Literal["cta_line", "strongest_line", "stats_card", "loop", "fade_out"]
    cta_examples: list[str]


class StyleProfile(BaseModel):
    name: str = Field(description="a short original name for this style, e.g. 'Road Log'")
    summary: str = Field(description="3-5 plain sentences a creator would understand")
    pacing: Pacing
    captions: Captions
    hook: Hook
    look: Look
    sound: Sound
    ending: Ending
    do: list[str] = Field(description="concrete rules to follow")
    dont: list[str] = Field(description="concrete things to avoid, including copying the references")


class StyleQuestion(BaseModel):
    id: str = Field(description="short slug, e.g. 'reel_type'")
    question: str
    options: list[str] = Field(description="2-4 short answers the user can tap")
    why: str = Field(description="what in the references was ambiguous")


class StyleAnalysis(BaseModel):
    profile: StyleProfile
    reference_notes: list[str] = Field(description="one line per reference: what was taken from it")
    questions: list[StyleQuestion] = Field(description="exactly 3 questions about real ambiguities")
