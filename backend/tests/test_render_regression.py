"""Regression: a plan mixing a shot that keeps its own (AAC) sound with silent shots, plus an
early caption, used to hang the final ffmpeg step (stream-copy concat shifted timestamps).
Renders a small preview with ffmpeg (~15 s, no network)."""
import subprocess
from pathlib import Path

from app.services import analysis as A
from app.services import render as R
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, validate


def test_render_keep_audio_with_early_caption(tmp_path: Path):
    work = tmp_path


    def ff(*a):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


    a, land, b, c = (work / n for n in ("a.mp4", "land.mp4", "b.mp4", "c.mp4"))
    ff("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30", "-f", "lavfi", "-i", "anoisesrc=a=0.01", "-t", "4",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(a))
    ff("-f", "lavfi", "-i", "smptebars=size=1920x1080:rate=30", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(land))
    ff("-display_rotation:v:0", "90", "-i", str(land), "-c", "copy", str(b))
    ff("-f", "lavfi", "-i", "mandelbrot=size=1080x1920:rate=30", "-f", "lavfi", "-i", "sine=frequency=330", "-t", "5",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(c))
    src = {}
    for alias, f in (("C1", a), ("C2", b), ("C3", c)):
        p = A.make_proxy(f, work / f"{alias}-proxy.mp4")
        src[alias] = (p, A.has_audio_stream(p))


    def shot(cl, x, y, **kw):
        return {"clip": cl, "in_s": x, "out_s": y, "speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0,
                "focus_x": 0.5, "focus_y": 0.5, "keep_audio": False, "purpose": "", **kw}


    plan = EditPlan.model_validate({
        "title": "E2E", "summary": "",
        "shots": [shot("C1", 0.2, 3.2), shot("C2", 0, 2.5, zoom_to=1.3),
                  shot("C3", 0.5, 4.5, speed=0.8, keep_audio=True, zoom_from=1.6, zoom_to=1.8)],
        "captions": [{"text": "Day 1.", "start_s": 0.3, "end_s": 2.0, "position": "lower_middle", "highlight": None}],
        "overlays": [{"type": "stats_card", "start_s": 10.5, "end_s": 13.5, "title": "E2E", "items": []}],
        "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0.5,
    })
    plan, warnings, tl = validate(plan, {k: ClipInfo(k, 5.0 if k == "C3" else (4.0 if k == "C1" else 3.0)) for k in src}, None)
    res = R.render(plan, tl, src, None, work / "out", quality="preview")
    assert abs(res.duration_s - 13.5) < 0.1
