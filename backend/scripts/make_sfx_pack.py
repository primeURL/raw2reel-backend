#!/usr/bin/env python3
"""Build the sound effects pack in app/assets/sfx with earshot (MIT, github.com/Leonxlnx/earshot).

earshot renders sounds from code (realistic ones rebuilt from public-domain recordings); what
it renders belongs to whoever renders it, free for commercial use, no credit needed. We render
the pack once and ship the small files, so the server needs none of earshot's ~480 MB of
libraries. Re-run only to change the pack:

    docker run --rm -v /path/to/earshot:/src:ro -v $PWD:/work -w /work python:3.12-slim sh -c \
      "apt-get update -qq && apt-get install -y -qq ffmpeg && pip install -q /src && python scripts/make_sfx_pack.py"
"""

from pathlib import Path

from earshot.make import make

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "sfx"
TAKES = 3  # different takes of each, so a reel with three punch-ins doesn't repeat one sound
SEED = 2026

# our name -> earshot design id
PACK = {
    "whoosh_fast": "whoosh/fast",   # punch in
    "whoosh_soft": "whoosh/soft",   # slow push
    "boom": "boom/deep",            # spotlight: lights out
    "slam": "slam/title",           # word behind you lands, flash
    "shutter": "camera/shutter",    # freeze frame
    "tick": "clock/tick",           # countdown
    "pop": "pop/soft",              # captions appearing (punchy)
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, design in PACK.items():
        r = make(sound=design, out=str(OUT / f"{name}.ogg"), n=TAKES, seed=SEED, mono=True, lufs=-14)
        print(name, "<-", r["sound"], [Path(f).name for f in r["files"]])


if __name__ == "__main__":
    main()
