"""Ready-made templates: complete styles for common reel types, so a creator can start without
learning a style from reference reels. Picking one copies it into the creator's own styles
(POST /v1/templates/{id}/use), where it works like any learned style.

Each is a full StyleProfile (validated in tests) plus a caption look and a music mood from the
library.
"""

from dataclasses import dataclass

from app.services.style_schema import StyleProfile


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    emoji: str
    tagline: str
    profile: dict


def _p(name, summary, *, reel_type="mixed", length=(15, 35), shots=(1.2, 3.0), on_beat=True, dead_air="cut_tight",
       look="clean_bold", size="medium", case="sentence", position="lower_middle", animation="pop", mode="phrase",
       max_words=5, highlight=True, hook="strongest_shot", title_card=False, grade="natural", zooms="punch_in_on_emphasis",
       transitions="mixed", accent="#FF5A1F", music="under_voice", mood="upbeat", sfx="subtle", ending="cta_line",
       ctas=("Save this for later", "Follow for more"), do=(), dont=()) -> dict:
    return {
        "name": name, "summary": summary,
        "pacing": {"reel_type": reel_type, "target_length_s": list(length), "shot_length_s": list(shots),
                   "cut_on_beat": on_beat, "dead_air": dead_air, "notes": ""},
        "captions": {"enabled": True, "mode": mode, "max_words_on_screen": max_words, "size": size, "weight": "bold",
                     "case": case, "position": position, "animation": animation, "look": look,
                     "keyword_highlight": highlight, "text_color": "#FFFFFF", "font_feel": "", "language_script": "as_spoken"},
        "hook": {"style": hook, "title_card": title_card, "notes": ""},
        "look": {"grade": grade, "letterbox": False, "zooms": zooms, "transitions": transitions, "overlays": [],
                 "accent_color": accent},
        "sound": {"music": music, "music_mood": mood, "keep_original_audio": True, "sound_effects": sfx},
        "ending": {"style": ending, "cta_examples": list(ctas)},
        "do": list(do), "dont": list(dont),
    }


TEMPLATES: list[Template] = [
    Template("recipe", "Recipe", "🍳", "Step by step, warm and tasty", _p(
        "Recipe", "Each step of the dish in order, close shots of the food, short punchy captions naming each step.",
        look="pop_box", grade="warm", mood="upbeat", sfx="frequent", accent="#FF7A1A", hook="result_first",
        ctas=("Save this recipe", "Try it and tag me"),
        do=["Show the finished dish first for a second, then go step by step", "One step per caption, name the ingredient"],
        dont=["No long pauses while stirring"])),
    Template("workout", "Workout day", "💪", "Fast cuts, big words, hype", _p(
        "Workout day", "High-energy training reel: fast cuts on the beat, bold upper-case captions, punchy sounds.",
        look="punch", case="upper", grade="high_contrast", transitions="whip", mood="energetic", sfx="frequent",
        shots=(0.6, 1.8), accent="#FFD400", hook="bold_claim_title", ctas=("Follow for day 2", "Save this workout"),
        do=["Cut on every rep or beat", "Put the numbers (reps, km, kg) on screen"])),
    Template("tips", "Quick tips", "💡", "Talking to camera, karaoke captions", _p(
        "Quick tips", "Someone talking to camera with tight cuts, captions that follow every word, a zoom on the key point.",
        reel_type="talking_tips", look="karaoke", case="upper", animation="karaoke", max_words=4, mode="phrase",
        transitions="hard_cuts", music="under_voice", mood="lofi", sfx="subtle", hook="face_and_line",
        do=["Cut every pause and restart", "Punch in on the main point"], dont=["No music louder than the voice"])),
    Template("vlog", "Day in my life", "☀️", "Easy, warm and personal", _p(
        "Day in my life", "A relaxed day told in moments: soft transitions, warm colour, clean captions.",
        look="clean_bold", grade="warm", transitions="dissolves", zooms="slow_push", mood="chill", sfx="subtle",
        animation="fade", length=(20, 45), shots=(1.5, 3.5), ctas=("What should I do tomorrow?",))),
    Template("travel", "Travel", "✈️", "Cinematic, music-led", _p(
        "Travel", "Wide, beautiful shots cut to the music with few words: a place, a feeling, a line or two.",
        reel_type="cinematic", look="cinema", case="upper", position="middle", animation="fade", max_words=4,
        highlight=False, grade="muted_film", zooms="slow_push", transitions="dissolves", music="music_led", mood="cinematic",
        sfx="none", shots=(1.5, 3.5), ending="fade_out", hook="strongest_shot")),
    Template("festival", "Festival", "🪔", "Desi celebration, bright and full", _p(
        "Festival", "Celebration reel: colour, people, lights and dhol, bright captions with a desi feel.",
        look="desi_bold", grade="warm", transitions="mixed", mood="desi", sfx="subtle", accent="#FF9933",
        ctas=("Happy festival from us!", "Share with family"))),
    Template("comedy", "Funny", "😂", "Comic captions, quick timing", _p(
        "Funny", "Comedy timing: quick cuts, big comic captions, sound effects on every joke.",
        look="comic", case="upper", grade="natural", transitions="whip", mood="funny", sfx="frequent", accent="#FFD400",
        shots=(0.8, 2.2), hook="face_and_line")),
    Template("tech", "Tech review", "📱", "Clean, techy and precise", _p(
        "Tech review", "Product close-ups and clear points, monospaced captions with a highlighted spec.",
        reel_type="talking_tips", look="mono", grade="cool", transitions="hard_cuts", mood="lofi", sfx="subtle",
        accent="#3DFF6B", hook="result_first", ctas=("Would you buy it?", "Follow for honest reviews"))),
    Template("story", "Storytime", "📖", "Subtitles you can read, emotional", _p(
        "Storytime", "A story told to camera with readable boxed subtitles; natural pauses kept for feeling.",
        reel_type="talking_tips", look="subtitle_box", animation="none", dead_air="keep_natural_pauses", transitions="hard_cuts",
        zooms="slow_push", mood="emotional", sfx="none", length=(30, 60), ending="strongest_line")),
    Template("aesthetic", "Aesthetic", "🌸", "Soft, slow and lowercase", _p(
        "Aesthetic", "Slow, soft visuals with lowercase serif captions and gentle music.",
        reel_type="cinematic", look="editorial", case="lower", animation="fade", position="middle", highlight=False,
        grade="muted_film", zooms="slow_push", transitions="dissolves", music="music_led", mood="chill", sfx="none",
        shots=(1.8, 4.0), ending="fade_out")),
    Template("news", "Breaking", "📰", "Bold headline energy", _p(
        "Breaking", "News-style: a strong headline hook, boxed captions, tension music and hard cuts.",
        look="news", case="upper", animation="slide_up", grade="high_contrast", transitions="hard_cuts", mood="dramatic",
        sfx="subtle", accent="#E0201B", hook="bold_claim_title", title_card=True)),
    Template("motivation", "Motivation", "🔥", "Big words, rising music", _p(
        "Motivation", "Inspiring lines in huge condensed type over strong shots, music rising to the end.",
        look="beast", case="upper", position="middle", grade="high_contrast", transitions="mixed", music="music_led",
        mood="inspiring", sfx="subtle", accent="#3DFF6B", ending="strongest_line")),
    Template("launch", "Product launch", "🚀", "Neon, energetic reveal", _p(
        "Product launch", "Reveal the product with energy: neon captions, quick cuts, a big hit on the reveal.",
        look="neon", grade="cool", transitions="mixed", mood="energetic", sfx="frequent", accent="#00E5FF",
        hook="result_first", ctas=("Link in bio", "Get yours today"))),
]

BY_ID = {t.id: t for t in TEMPLATES}


def get(template_id: str) -> Template | None:
    return BY_ID.get(template_id)


def validated(t: Template) -> dict:
    return StyleProfile.model_validate(t.profile).model_dump()
