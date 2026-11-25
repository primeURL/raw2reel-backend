"""Phase 2: caption looks, karaoke captions and ready-made templates. ~20 s, no network."""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from app.services import analysis as A
from app.services import caption_looks as CL
from app.services import graphics as G
from app.services import render as R
from app.services import templates as T
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, validate
from app.services.style_schema import StyleProfile

ASSETS = Path(__file__).resolve().parent.parent / "app" / "assets"


def test_every_look_draws_english_and_hindi(tmp_path: Path):
    for lk in CL.LOOKS:
        assert Path(lk.font_path()).exists(), lk.id
        for text in ("Chop the fresh fruit", "आज का नाश्ता ready hai"):
            png = G.caption_png(text, tmp_path / f"{lk.id}.png", position="middle", highlight="fresh", look=lk)
            alpha = np.asarray(Image.open(png).getchannel("A"))
            assert (alpha > 200).sum() > 2000, (lk.id, text)  # something solid was drawn
            box = Image.open(png).getchannel("A").getbbox()
            assert G.SAFE_TOP <= box[1] and box[3] <= G.SAFE_BOTTOM + 40, (lk.id, box)


def test_preview_images_exist_for_every_look_and_template():
    assert {p.stem for p in (ASSETS / "looks").glob("*.jpg")} >= set(CL.LOOK_IDS)
    assert {p.stem for p in (ASSETS / "templates").glob("*.jpg")} >= set(T.BY_ID)


def test_highlight_box_marks_the_word(tmp_path: Path):
    lk = CL.get("pop_box")
    plain = np.asarray(Image.open(G.caption_png("Chop the fresh fruit", tmp_path / "a.png", position="middle", look=lk)))
    boxed = np.asarray(Image.open(G.caption_png("Chop the fresh fruit", tmp_path / "b.png", position="middle",
                                                highlight="fresh", look=lk, accent="#FF5A1F")))
    orange = lambda a: int(((a[..., 0] > 200) & (a[..., 1] < 140) & (a[..., 2] < 90) & (a[..., 3] > 200)).sum())  # noqa: E731
    assert orange(boxed) > orange(plain) + 3000  # a solid accent box behind the word


def test_karaoke_moves_the_highlight(tmp_path: Path):
    lk = CL.get("karaoke")
    first = G.caption_png("one two three", tmp_path / "k0.png", position="middle", look=lk, active_word=0)
    last = G.caption_png("one two three", tmp_path / "k2.png", position="middle", look=lk, active_word=2)

    def accent_x(p: Path) -> float:
        a = np.asarray(Image.open(p))
        mask = (a[..., 0] > 200) & (a[..., 1] < 140) & (a[..., 3] > 200)
        return float(np.nonzero(mask)[1].mean())
    assert accent_x(first) < G.W / 2 < accent_x(last)


def test_templates_are_complete_styles():
    assert len(T.TEMPLATES) >= 12
    for t in T.TEMPLATES:
        prof = StyleProfile.model_validate(t.profile)
        assert prof.captions.look in CL.BY_ID, t.id
        assert t.profile["sound"]["music_mood"] in ("upbeat", "energetic", "chill", "lofi", "emotional", "cinematic",
                                                    "inspiring", "funny", "desi", "dramatic"), t.id


def test_old_styles_without_a_look_still_load():
    prof = T.validated(T.get("vlog"))
    prof["captions"].pop("look")
    assert StyleProfile.model_validate(prof).captions.look is None


def test_creator_can_pick_a_look():
    from app.services import prefs as P

    merged = P.merged_style({"captions": {"look": "clean"}}, {"captions": {"look": "comic", "animation": "karaoke"}})
    assert merged["captions"]["look"] == "comic" and merged["captions"]["animation"] == "karaoke"


def test_karaoke_render(tmp_path: Path):
    raw = tmp_path / "C1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:size=1080x1920:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=220", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(raw)], check=True)
    src = {"C1": (A.make_proxy(raw, tmp_path / "C1_p.mp4"), True)}
    shot = {"speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0, "focus_x": 0.5, "focus_y": 0.5, "keep_audio": True, "purpose": "",
            "transition_in": "cut", "clip": "C1", "in_s": 0, "out_s": 3}
    plan = EditPlan.model_validate({
        "title": "t", "summary": "", "shots": [shot], "overlays": [], "effects": [], "sound_effects": "off", "sounds": [],
        "captions": [{"text": "left middle right", "start_s": 0.0, "end_s": 3.0, "position": "middle", "highlight": None}],
        "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0})
    plan, _, tl = validate(plan, {"C1": ClipInfo("C1", 4.0)}, None)
    res = R.render(plan, tl, src, {"captions": {"look": "karaoke"}, "look": {"accent_color": "#FF5A1F"}},
                   tmp_path / "out", quality="preview")

    def accent_x(t: str) -> float:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(res.path), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        f = np.frombuffer(raw, np.uint8).reshape(960, 540, 3).astype(int)
        mask = (f[..., 0] > 190) & (f[..., 1] < 140) & (f[..., 2] < 110)
        return float(np.nonzero(mask)[1].mean())
    assert accent_x("0.4") < accent_x("1.5") < accent_x("2.7")  # the box walks left to right with the words
