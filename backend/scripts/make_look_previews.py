#!/usr/bin/env python3
"""Draw a preview of every caption look with the real caption renderer, for the app's look picker.

    docker compose run --rm -v "$PWD":/app worker-media python scripts/make_look_previews.py

Writes app/assets/looks/<id>.jpg (480x270: the middle of a 1080x1920 frame) and a contact sheet
work/looks_sheet.jpg to eyeball them all at once. Re-run after adding or changing a look.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

from app.services import caption_looks as CL  # noqa: E402
from app.services import graphics as G  # noqa: E402
from app.services import templates as T  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "looks"
TPL_OUT = OUT.parent / "templates"
SAMPLES = {  # a line that sounds like each template, and its key word
    "recipe": ("Step 2: add the masala", "masala"), "workout": ("100 push-ups done", "100"),
    "tips": ("Stop doing this every morning", "this"), "vlog": ("Slow morning chai first", "chai"),
    "travel": ("Lost in the mountains", None), "festival": ("Diwali ki raat", "Diwali"),
    "comedy": ("When mom finds the remote", "mom"), "tech": ("12 hours of battery", "12"),
    "story": ("This changed everything for me", "everything"), "aesthetic": ("little things that matter", None),
    "news": ("Prices just dropped 50%", "50%"), "motivation": ("Nobody is coming to save you", "Nobody"),
    "launch": ("Meet the new one", "new"),
}
GRADE_TINT = {"warm": (255, 170, 90), "cool": (90, 160, 255), "muted_film": (170, 160, 140), "high_contrast": (40, 40, 40),
              "black_and_white": (128, 128, 128), "natural": None}
TEXT, HIGHLIGHT = "Chop the fresh fruit first", "fresh"
CROP = (130, 773, 950, 1234)  # 16:9, tight around the middle caption position (the safe width)
ACCENT = "#FF5A1F"


def background() -> Image.Image:
    """A soft, photo-like warm kitchen blur (no real photo needed): light and dark areas both,
    so a look has to read on either."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:G.H, 0:G.W]
    base = np.stack([
        150 + 60 * np.sin(x / 260) + 30 * np.cos(y / 300),
        110 + 40 * np.sin(x / 330 + 1) + 25 * np.cos(y / 210),
        80 + 30 * np.cos(x / 400 + 2) + 20 * np.sin(y / 260),
    ], axis=-1)
    for _ in range(14):  # a few soft blobs, like out-of-focus objects
        cx, cy, r = rng.integers(0, G.W), rng.integers(500, 1500), rng.integers(80, 260)
        blob = np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r)))[..., None]
        base = base * (1 - 0.6 * blob) + rng.integers(30, 240, 3) * 0.6 * blob
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(12))
    return img.convert("RGBA")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bg = background()
    tmp = Path("/tmp/look_previews")
    tmp.mkdir(exist_ok=True)
    tiles = []
    for lk in CL.LOOKS:
        layer = G.caption_png(TEXT, tmp / f"{lk.id}.png", position="middle", size="medium", accent=ACCENT,
                              highlight=HIGHLIGHT, look=lk, active_word=2 if lk.animation == "karaoke" else None)
        frame = bg.copy()
        frame.alpha_composite(Image.open(layer))
        tile = frame.crop(CROP).convert("RGB").resize((480, 270), Image.LANCZOS)
        tile.save(OUT / f"{lk.id}.jpg", quality=86)
        tiles.append(tile)
        print("drew", lk.id)
    template_covers(bg)
    cols = 4
    sheet = Image.new("RGB", (480 * cols, 270 * ((len(tiles) + cols - 1) // cols)), "black")
    for i, t in enumerate(tiles):
        sheet.paste(t, (480 * (i % cols), 270 * (i // cols)))
    Path("work").mkdir(exist_ok=True)
    sheet.save("work/looks_sheet.jpg", quality=80)
    print(f"{len(tiles)} looks -> {OUT}")


def template_covers(bg: Image.Image) -> None:
    """9:16 cover per template: the backdrop tinted to its colour look, its caption look on a line in its voice."""
    TPL_OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path("/tmp/look_previews")
    for t in T.TEMPLATES:
        prof = t.profile
        frame = bg.copy()
        tint = GRADE_TINT.get(prof["look"]["grade"])
        if tint:
            frame = Image.blend(frame, Image.new("RGBA", frame.size, (*tint, 255)), 0.28)
        text, hl = SAMPLES.get(t.id, (t.name, None))
        cap = prof["captions"]
        layer = G.caption_png(text, tmp / f"tpl_{t.id}.png", position=cap["position"], size="large",
                              accent=prof["look"]["accent_color"], highlight=hl, case=cap["case"],
                              look=CL.get(cap["look"]), active_word=1 if cap["animation"] == "karaoke" else None)
        frame.alpha_composite(Image.open(layer))
        frame.convert("RGB").resize((270, 480), Image.LANCZOS).save(TPL_OUT / f"{t.id}.jpg", quality=84)
        print("cover", t.id)


if __name__ == "__main__":
    main()
