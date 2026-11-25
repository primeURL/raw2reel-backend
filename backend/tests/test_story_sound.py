"""The AI-first edit: story beats, transitions between clips, the editor's own sound design and
animated captions - validated, mixed and rendered. ~25 s, no network."""
import subprocess
from pathlib import Path

import numpy as np

from app.services import analysis as A
from app.services import render as R
from app.services import sfx as S
from app.services.plan_schema import AIEditPlan, EditPlan
from app.services.plan_validate import ClipInfo, validate

SHOT = {"speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0, "focus_x": 0.5, "focus_y": 0.5, "keep_audio": True, "purpose": ""}


def _plan(**over) -> EditPlan:
    base = {
        "title": "Breakfast", "summary": "",
        "story": [{"beat": "chop fruit", "clips": ["C2"]}, {"beat": "oats in milk", "clips": ["C1"]}],
        "shots": [{"clip": "C2", "in_s": 0, "out_s": 3, "transition_in": "whip", **SHOT},
                  {"clip": "C1", "in_s": 0, "out_s": 3, "transition_in": "whip", **SHOT},
                  {"clip": "C1", "in_s": 3, "out_s": 5, "transition_in": "zoom", **SHOT}],
        "captions": [{"text": "Chop the fruit", "start_s": 0.2, "end_s": 1.8, "position": "middle", "highlight": "fruit"},
                     {"text": "Oats in milk", "start_s": 3.2, "end_s": 4.8, "position": "middle", "highlight": "Oats"}],
        "overlays": [], "effects": [], "sound_effects": "punchy",
        "sounds": [{"at_s": 3.0, "sound": "whoosh_fast", "level": "normal", "why": "whip to the oats"},
                   {"at_s": 3.1, "sound": "pop", "level": "soft", "why": "too close"},
                   {"at_s": 3.3, "sound": "pop", "level": "soft", "why": "oats appear"},
                   {"at_s": 99, "sound": "slam", "level": "loud", "why": "past the end"}],
        "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0.3,
    }
    base.update(over)
    return EditPlan.model_validate(base)


CLIPS = {"C1": ClipInfo("C1", 6.0), "C2": ClipInfo("C2", 6.0)}


def test_ai_must_decide_story_transitions_and_sounds():
    schema = AIEditPlan.model_json_schema()
    assert {"story", "sounds", "effects"} <= set(schema["required"])
    assert "transition_in" in schema["$defs"]["AIShot"]["required"]


def test_old_plans_still_load():
    p = EditPlan.model_validate({**_plan().model_dump(exclude={"story", "sounds"}),
                                 "shots": [{"clip": "C1", "in_s": 0, "out_s": 2, **SHOT}]})
    assert p.story == [] and p.sounds == [] and p.shots[0].transition_in == "cut"


def test_validator_cleans_transitions_and_sounds():
    plan, _, _ = validate(_plan(), CLIPS, None)
    assert [s.transition_in for s in plan.shots] == ["cut", "whip", "cut"]  # first shot; continuous take
    assert [(c.at_s, c.sound) for c in plan.sounds] == [(3.0, "whoosh_fast"), (3.3, "pop")]
    off, _, _ = validate(_plan(sound_effects="off"), CLIPS, None)
    assert off.sounds == []


def test_keyword_style_keeps_every_highlight():
    style = {"captions": {"keyword_highlight": True}, "look": {"accent_color": "#FF5A1F"}}
    plan, _, _ = validate(_plan(), CLIPS, style)
    assert [c.highlight for c in plan.captions] == ["fruit", "Oats"]
    plain, _, _ = validate(_plan(), CLIPS, {"captions": {"keyword_highlight": False}, "look": {"accent_color": "#FF5A1F"}})
    assert [c.highlight for c in plain.captions] == ["fruit", None]


def test_mix_uses_the_editors_sounds_else_the_rules():
    plan, _, _ = validate(_plan(), CLIPS, None)
    assert [(c.name, c.at_s, c.gain_db) for c in S.cues(plan, 8)] == [("whoosh_fast", 3.0, 0.0), ("pop", 3.3, -5.0)]
    ruled = _plan(sounds=[], sound_effects="subtle")  # punchy would also pop captions in
    assert S.transition_times(ruled) == [(3.0, "whip"), (6.0, "zoom")]
    assert [(c.name, c.at_s) for c in S.cues(ruled, 8)] == [("whoosh_fast", 3.0), ("whoosh_fast", 6.0)]


def test_transitions_and_animated_captions_render(tmp_path: Path):
    srcs = {}
    for alias, color in (("C1", "red"), ("C2", "blue")):
        raw = tmp_path / f"{alias}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:size=1080x1920:rate=30",
                        "-f", "lavfi", "-i", "sine=frequency=220", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(raw)], check=True)
        srcs[alias] = (A.make_proxy(raw, tmp_path / f"{alias}_p.mp4"), True)
    plan, _, tl = validate(_plan(shots=[{"clip": "C2", "in_s": 0, "out_s": 3, "transition_in": "cut", **SHOT},
                                        {"clip": "C1", "in_s": 0, "out_s": 3, "transition_in": "flash", **SHOT}]), CLIPS, None)
    style = {"captions": {"animation": "pop", "keyword_highlight": True}}
    res = R.render(plan, tl, srcs, style, tmp_path / "out", quality="preview")
    assert abs(res.duration_s - 6.0) < 0.1

    def frame(t: str) -> np.ndarray:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(res.path), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(960, 540, 3)

    assert frame("3.0").mean() > 200  # the flash: near white right at the cut
    assert frame("2.0")[50, 50, 2] > 150 and frame("4.5")[50, 50, 0] > 150  # blue clip first, then red (story order)
    # the caption pops in: a few frames after it starts it's smaller than when it has settled
    def ink(t: str) -> int:
        f = frame(t)
        return int(((f > 200).all(axis=2)).sum())  # white caption pixels
    assert 0 < ink("0.27") < ink("1.0")


def test_revision_sends_the_current_edit_and_the_request(monkeypatch):
    from app.services import plan_ai

    seen = {}

    def fake_parse(system, content, fmt, effort):
        seen["system"], seen["text"] = system, " ".join(b.get("text", "") for b in content if b["type"] == "text")
        plan = _plan().model_dump()
        return fmt.model_validate({"changes": ["Oats scene now comes first", " "], "lesson": "", "lesson_applies_to": "all",
                                   "lesson_rule": "none", "plan": plan}), {"model": "x"}

    monkeypatch.setattr(plan_ai, "_parse", fake_parse)
    clip = plan_ai.ClipInput("C1", 6.0, b"jpg", False, [], [], [])
    plan, changes, _, lesson = plan_ai.revise_plan([clip], None, "Breakfast", None, "en", None, {"shots": []}, "put the oats first")
    assert "Revising" in seen["system"]
    assert "Current edit" in seen["text"] and "The creator asks: put the oats first" in seen["text"]
    assert changes == ["Oats scene now comes first"] and lesson is None  # blank ones dropped; nothing to learn
    assert plan.story[0].beat == "chop fruit"


def test_creator_choices_fold_into_the_style_and_win():
    from app.services import prefs as P

    style = {"captions": {"animation": "fade", "keyword_highlight": False, "size": "small"}, "look": {"transitions": "hard_cuts"}}
    choices = {"captions": {"animation": "typewriter", "highlight": True, "size": None}, "sound_effects": "off",
               "transitions": "energetic", "effects": "none"}
    merged = P.merged_style(style, choices)
    assert merged["captions"] == {"animation": "typewriter", "keyword_highlight": True, "size": "small"}
    assert merged["look"]["transitions"] == "mixed" and merged["sound"]["sound_effects"] == "none"
    assert style["captions"]["animation"] == "fade"  # the saved style itself is untouched
    assert "No effects" not in (P.ai_note(choices) or "") and "effects = []" in P.ai_note(choices)
    plan = _plan(effects=[{"type": "flash", "start_s": 1, "end_s": 1.2}])
    P.enforce(plan, {"captions": {"enabled": False}, "sound_effects": "off", "transitions": "cuts", "effects": "none"})
    assert plan.captions == [] and plan.sounds == [] and plan.effects == []
    assert {s.transition_in for s in plan.shots} == {"cut"}
    assert P.merged_style(None, None) is None and P.merged_style(style, {}) is style


def test_typewriter_reveals_words_in_place(tmp_path: Path):
    from app.services import graphics as G

    full = G.caption_png("Oats in warm milk", tmp_path / "full.png", position="middle")
    center = G.layer_center_y(full)
    steps = [G.caption_png("Oats in warm milk", tmp_path / f"w{k}.png", position="middle", center_y=center, visible_words=k)
             for k in (1, 2, 4)]
    from PIL import Image
    boxes = [Image.open(p).getchannel("A").getbbox() for p in steps]
    widths = [b[2] - b[0] for b in boxes]
    assert widths[0] < widths[1] < widths[2]  # more words, more ink
    assert boxes[0][0] == boxes[2][0] or abs(boxes[0][0] - boxes[2][0]) < 3  # first word stays where it is in the full line
    assert abs(boxes[2][1] - Image.open(full).getchannel("A").getbbox()[1]) < 6  # same height as the full caption


def test_typewriter_renders(tmp_path: Path):
    raw = tmp_path / "C1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:size=1080x1920:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=220", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(raw)], check=True)
    src = {"C1": (A.make_proxy(raw, tmp_path / "C1_p.mp4"), True)}
    plan, _, tl = validate(_plan(shots=[{"clip": "C1", "in_s": 0, "out_s": 3, "transition_in": "cut", **SHOT}],
                                 captions=[{"text": "Oats in warm milk", "start_s": 0.5, "end_s": 2.5, "position": "middle", "highlight": None}],
                                 sounds=[]), {"C1": ClipInfo("C1", 4.0)}, None)
    res = R.render(plan, tl, src, {"captions": {"animation": "typewriter"}}, tmp_path / "out", quality="preview")

    def ink(t: str) -> int:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(res.path), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(960, 540, 3)
        return int((f > 230).all(axis=2).sum())
    first, later, full = ink("0.55"), ink("0.85"), ink("2.0")
    assert 0 < first < later < full, (first, later, full)
