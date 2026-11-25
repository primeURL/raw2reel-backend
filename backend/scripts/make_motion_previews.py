#!/usr/bin/env python3
"""Animated preview of every motion effect (its sample inputs over a soft backdrop), for the app's
effect gallery: app/assets/motion_previews/<type>.webp, 270x480, looping.

    docker compose run --rm -v "$PWD":/app worker-media python scripts/make_motion_previews.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from app.services import motion as M  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "motion_previews"
W, H, FPS, DUR = 270, 480, 15, 3.0


def backdrop() -> Image.Image:
    top, bottom = (58, 72, 96), (120, 86, 74)
    img = Image.new("RGBA", (W, H))
    for y in range(H):
        k = y / (H - 1)
        img.paste(tuple(int(a + (b - a) * k) for a, b in zip(top, bottom)) + (255,), (0, y, W, y + 1))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bg = backdrop()
    with tempfile.TemporaryDirectory() as d, M.Browser() as browser:
        for kind, (_, _, sample) in M.CATALOG.items():
            fx = {"title": sample.get("text", ""), "items": sample.get("items", []), "numbers": sample.get("numbers", []),
                  "unit": sample.get("unit", ""), "position": "middle", "accent": "#FF5A1F", "duration": DUR}
            frames = browser.render(kind, fx, W, H, FPS, Path(d) / kind)
            comp = Path(d) / f"{kind}_c"
            comp.mkdir()
            for k in range(frames.count):
                f = bg.copy()
                f.alpha_composite(Image.open(frames.folder / f"{k:04d}.png"))
                f.convert("RGB").save(comp / f"{k:04d}.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(comp / "%04d.png"),
                            "-c:v", "libwebp_anim", "-loop", "0", "-q:v", "70", "-preset", "picture",
                            str(OUT / f"{kind}.webp")], check=True)
            print(kind, (OUT / f"{kind}.webp").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
