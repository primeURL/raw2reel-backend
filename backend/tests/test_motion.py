"""Phase 3: motion-graphics effects rendered in headless Chromium and laid into the reel. ~40 s."""
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.services import analysis as A
from app.services import motion as MO
from app.services import render as R
from app.services import sfx as S
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, validate

SHOT = {"speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0, "focus_x": 0.5, "focus_y": 0.5, "keep_audio": True, "purpose": "",
        "transition_in": "cut", "clip": "C1", "in_s": 0, "out_s": 4}


def _plan(effects) -> EditPlan:
    return EditPlan.model_validate({
        "title": "t", "summary": "", "shots": [SHOT], "captions": [], "overlays": [], "effects": effects,
        "sound_effects": "subtle", "sounds": [], "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0})


def test_every_template_exists():
    for kind in MO.MOTION_TYPES:
        assert (MO.ASSETS / f"{kind}.html").exists(), kind


def test_counter_counts_and_is_transparent(tmp_path: Path):
    fx = {"title": "Push-ups", "items": [], "numbers": [0, 100], "unit": "", "position": "top", "accent": "#FF5A1F", "duration": 2.0}
    fr = MO.render("counter", fx, 540, 960, 10, tmp_path / "c")
    assert fr.count == 20
    first, last = (np.asarray(Image.open(fr.at(t))) for t in (0.0, 1.5))
    assert first.shape == (960, 540, 4)
    assert last[..., 3][700:].max() == 0  # nothing drawn low in the frame: the counter sits at the top
    orange = lambda a: int(((a[..., 0] > 200) & (a[..., 1] < 140) & (a[..., 3] > 200)).sum())  # noqa: E731
    assert orange(last) > orange(first)  # "100" in the accent colour is wider than "0"


def test_validator_tidies_motion_effects():
    plan = _plan([
        {"type": "chat", "start_s": 0.2, "end_s": 0.5, "items": ["hi", "  ", "x" * 200, *["m"] * 9], "numbers": [], "text": "Gym"},
        {"type": "counter", "start_s": 1.0, "end_s": 3.0, "numbers": [0, 10], "unit": " reps ", "position": "top"},
        {"type": "punch_in", "start_s": 1.0, "end_s": 1.8, "items": ["stray"], "behind": True},
    ])
    out, warnings, _ = validate(plan, {"C1": ClipInfo("C1", 6.0)}, None)
    chat, punch = next(e for e in out.effects if e.type == "chat"), next(e for e in out.effects if e.type == "punch_in")
    assert chat.end_s - chat.start_s >= 1.5 and len(chat.items) == 6 and len(chat.items[1]) == 70
    assert [e.type for e in out.effects if e.type in MO.MOTION_TYPES] == ["chat"]  # the counter clashed with the chat at the top
    assert any("same spot" in w for w in warnings)
    assert punch.items == [] and punch.behind is False


def test_motion_effects_get_a_sound():
    plan = _plan([{"type": "notification", "start_s": 1.0, "end_s": 3.0, "text": "Mom", "items": ["Hi"]}])
    assert [(c.name, c.at_s) for c in S.cues(plan, 4)] == [("ding", 1.1)]


@pytest.mark.parametrize("behind", [False, True])
def test_motion_effect_in_a_reel(tmp_path: Path, behind: bool):
    raw = tmp_path / "C1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=0x203040:size=1080x1920:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=220", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(raw)], check=True)
    src = {"C1": (A.make_proxy(raw, tmp_path / "C1_p.mp4"), True)}
    plan, _, tl = validate(_plan([{"type": "price_tag", "start_s": 1.0, "end_s": 3.0, "numbers": [499], "text": "SALE",
                                   "position": "middle", "behind": behind}]), {"C1": ClipInfo("C1", 5.0)}, None)
    res = R.render(plan, tl, src, None, tmp_path / "out", quality="preview")

    def orange_at(t: str) -> int:
        raw_ = subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(res.path), "-frames:v", "1", "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        f = np.frombuffer(raw_, np.uint8).reshape(960, 540, 3).astype(int)
        return int(((f[..., 0] > 200) & (f[..., 1] < 140) & (f[..., 2] < 100)).sum())
    assert orange_at("0.5") == 0
    assert orange_at("2.0") > 5000  # the price sticker is on screen (no person here, so behind changes nothing)
    assert orange_at("3.6") == 0
