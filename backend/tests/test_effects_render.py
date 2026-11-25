"""All eight effects render on a synthetic clip (no face in it, so they fall back to the
middle of the frame), the length is kept, and the quality checks come back. ~20 s, no network."""
import subprocess
from pathlib import Path

import numpy as np

from app.services import analysis as A
from app.services import render as R
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, validate


def test_every_effect_renders(tmp_path: Path):
    raw = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=220", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(raw)], check=True)
    proxy = A.make_proxy(raw, tmp_path / "proxy.mp4")
    plan = EditPlan.model_validate({
        "title": "FX", "summary": "",
        "shots": [{"clip": "C1", "in_s": 0, "out_s": 11, "speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0,
                   "focus_x": 0.5, "focus_y": 0.5, "keep_audio": True, "purpose": ""}],
        "captions": [{"text": "Every effect", "start_s": 0.2, "end_s": 2.0, "position": "middle", "highlight": None}],
        "overlays": [],
        "effects": [
            {"type": "punch_in", "start_s": 0.5, "end_s": 1.5},
            {"type": "spotlight", "start_s": 1.8, "end_s": 3.0},
            {"type": "grade", "start_s": 3.0, "end_s": 5.0, "look": "bw"},
            {"type": "freeze_frame", "start_s": 5.2, "end_s": 6.6, "text": "Look here"},
            {"type": "flash", "start_s": 6.8, "end_s": 7.1},
            {"type": "countdown", "start_s": 7.2, "end_s": 9.0},
            {"type": "slow_push", "start_s": 9.0, "end_s": 10.9},
            {"type": "backdrop_word", "start_s": 0.2, "end_s": 1.8, "text": "test"},
        ],
        "sound_effects": "punchy",
        "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0.5,
    })
    plan, warnings, tl = validate(plan, {"C1": ClipInfo("C1", 12.0)}, None)
    assert len(plan.effects) == 8, warnings
    stages = []
    res = R.render(plan, tl, {"C1": (proxy, True)}, None, tmp_path / "out", quality="preview",
                   progress=lambda f, s: stages.append((round(f, 2), s)))
    assert abs(res.duration_s - 11.0) < 0.1
    assert "Adding effects" in {s for _, s in stages}
    assert [f for f, _ in stages] == sorted(f for f, _ in stages)  # progress never goes back
    names = {c["name"]: c for c in res.checks}
    assert names["Length"]["ok"] and names["No clipping"]["ok"]
    assert names["Voice level"]["ok"], names["Voice level"]  # levelled to about -16 LUFS
    # freeze frame really holds still: two frames inside it are identical
    a, b = (subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(res.path), "-frames:v", "1", "-f", "rawvideo",
                            "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout for t in ("5.6", "6.2"))
    diff = np.abs(np.frombuffer(a, np.uint8).astype(int) - np.frombuffer(b, np.uint8).astype(int)).mean()
    assert diff < 1.5, diff  # same picture (only encoder noise); testsrc2 itself changes every frame
