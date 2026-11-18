"""The Road Log style written by hand on Day 1 must fit the schema Claude fills in."""

from app.services.style_schema import StyleAnalysis

ROAD_LOG = {
    "profile": {
        "name": "Road Log",
        "summary": "Cinematic running reels. Long outdoor shots, calm one-line captions, orange stats card at the end.",
        "pacing": {"reel_type": "cinematic", "target_length_s": [8, 20], "shot_length_s": [3, 10],
                   "cut_on_beat": True, "dead_air": "keep_natural_pauses", "notes": "let the movement breathe"},
        "captions": {"enabled": True, "mode": "full_line", "max_words_on_screen": 7, "size": "small",
                     "weight": "medium", "case": "sentence", "position": "lower_middle", "animation": "fade",
                     "keyword_highlight": True, "text_color": "#FFFFFF", "font_feel": "clean sans",
                     "language_script": "roman"},
        "hook": {"style": "strongest_shot", "title_card": False, "notes": "open on movement"},
        "look": {"grade": "natural", "letterbox": False, "zooms": "slow_push", "transitions": "hard_cuts",
                 "overlays": ["run stats card"], "accent_color": "#FF5A1F"},
        "sound": {"music": "music_led", "music_mood": "calm, rising", "keep_original_audio": False, "sound_effects": "none"},
        "ending": {"style": "stats_card", "cta_examples": ["Day 1. Kal phir."]},
        "do": ["one caption line at a time"],
        "dont": ["captions in the bottom 15%"],
    },
    "reference_notes": ["low ground angle and stats overlay"],
    "questions": [{"id": "reel_type", "question": "Cinematic or talking?", "options": ["Cinematic", "Talking", "Both"], "why": "mixed refs"}],
}


def test_road_log_fits():
    a = StyleAnalysis.model_validate(ROAD_LOG)
    assert a.profile.look.accent_color == "#FF5A1F"
    assert a.profile.captions.position == "lower_middle"


def test_json_schema_builds():
    schema = StyleAnalysis.model_json_schema()
    assert "profile" in schema["properties"]
