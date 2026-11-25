#!/usr/bin/env python3
"""Add downloaded music and sound effects to the sound library in R2.

Put the files in folders named after what they are, then run this once:

    sounds/
      music/upbeat/…mp3          one folder per mood (app/services/library.py MOODS);
      music/desi+upbeat/…mp3     '+' gives a track two moods
      sfx/whoosh_fast/…mp3       one folder per sound (plan_schema.SoundName)

    docker compose run --rm -v ~/Desktop/raw2reel-sounds:/sounds:ro worker-media \
        python scripts/import_sounds.py /sounds --source pixabay

Each file is levelled (music to -14 LUFS, effects so their loudest moment is -14 LUFS), music gets
its tempo and beats and a 20-second preview, and everything lands in R2 under library/ with a
record of where it came from. Files already in the library (same content) are skipped, so run it
again whenever you add more.

    --list            what's in the library
    --block ID        take a track out (e.g. it got a copyright claim); --unblock ID puts it back
    --dry-run         analyse and print, upload nothing
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import storage  # noqa: E402
from app.services import beats as B  # noqa: E402
from app.services import library as L  # noqa: E402
from app.services.plan_schema import SoundName  # noqa: E402

AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
SFX_NAMES = set(SoundName.__args__)
LICENCES = {"pixabay": "Pixabay Content License (pixabay.com/service/license-summary): free, no credit needed; "
                       "may not be redistributed on its own"}
PREVIEW_S = 20.0
MAX_SFX_S = 4.0


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pretty_title(stem: str) -> str:
    s = re.sub(r"[-_ ]\d{4,}$", "", stem)  # Pixabay names end in the item number
    s = re.sub(r"[-_]+", " ", s).strip()
    return s[:1].upper() + s[1:] if s else stem


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "sound"


def run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=600)


def level_music(src: Path, dest: Path, lufs: float) -> None:
    gain = -14.0 - lufs
    run(["-i", str(src), "-vn", "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=disabled",
         "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", str(dest)])


def make_preview(src: Path, dest: Path, a: B.Analysis) -> None:
    start = max(0.0, min(a.duration_s * 0.3, a.duration_s - PREVIEW_S))
    if a.beats:  # begin on a beat
        start = min(a.beats, key=lambda b: abs(b - start))
    d = min(PREVIEW_S, a.duration_s - start)
    run(["-ss", f"{start:.3f}", "-t", f"{d:.3f}", "-i", str(src), "-vn",
         "-af", f"afade=t=in:d=0.3,afade=t=out:st={max(0, d - 1.5):.3f}:d=1.5",
         "-ac", "2", "-c:a", "aac", "-b:a", "96k", str(dest)])


def level_sfx(src: Path, dest: Path) -> None:
    tmp = dest.with_name("trim_" + dest.name)
    run(["-i", str(src), "-vn", "-af", "silenceremove=start_periods=1:start_threshold=-50dB",
         "-t", str(MAX_SFX_S), "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "160k", str(tmp)])
    gain = -14.0 - B.momentary_max(tmp)
    run(["-i", str(tmp), "-af", f"volume={gain:.2f}dB,alimiter=limit=0.95:level=disabled,afade=t=out:st={MAX_SFX_S - 0.2}:d=0.2",
         "-c:a", "aac", "-b:a", "160k", str(dest)])
    tmp.unlink(missing_ok=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return round(float(out or 0), 2)


def load() -> dict:
    return L.manifest(fresh=True)


def save(data: dict) -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "manifest.json"
        p.write_text(json.dumps(data, indent=1))
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        storage.upload_file(p, f"library/history/manifest-{stamp}.json", "application/json")  # every version kept
        storage.upload_file(p, L.MANIFEST_KEY, "application/json")


def import_dir(root: Path, source: str, dry: bool) -> None:
    data = load()
    known = {t["sha1"] for t in data["music"] + data["sfx"]}
    today = dt.date.today().isoformat()
    added = skipped = 0
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        for kind in ("music", "sfx"):
            for folder in sorted(p for p in (root / kind).glob("*") if p.is_dir()):
                tags = [t.strip().lower() for t in folder.name.split("+") if t.strip()]
                bad = [t for t in tags if t not in (L.MOODS if kind == "music" else SFX_NAMES)]
                if bad:
                    print(f"!! skipping folder {folder}: unknown {'mood' if kind == 'music' else 'sound'} {bad}. "
                          f"Use: {', '.join(L.MOODS if kind == 'music' else sorted(SFX_NAMES))}")
                    continue
                for f in sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO):
                    digest = sha1(f)
                    if digest in known:
                        skipped += 1
                        continue
                    tid = f"{slug(pretty_title(f.stem))}-{digest[:8]}"
                    rec = {"id": tid, "title": pretty_title(f.stem), "source": source, "source_file": f.name,
                           "licence": LICENCES.get(source, source), "added": today, "sha1": digest}
                    if kind == "music":
                        a = B.analyse(f)
                        if a.duration_s < 8:
                            print(f"!! {f.name}: only {a.duration_s}s, too short for music - skipped")
                            continue
                        out, prev = tmp / f"{tid}.m4a", tmp / f"{tid}_preview.m4a"
                        level_music(f, out, a.lufs)
                        make_preview(out, prev, a)
                        rec.update(moods=tags, energy=a.energy, bpm=a.bpm, beats=a.beats, duration_s=duration(out),
                                   key=f"library/music/{tid}.m4a", preview_key=f"library/music/{tid}_preview.m4a")
                        print(f"+ music {tid}: {tags} {a.energy}, {a.bpm} BPM, {rec['duration_s']}s (was {a.lufs} LUFS)")
                        uploads = [(out, rec["key"]), (prev, rec["preview_key"])]
                    else:
                        out = tmp / f"{tid}.m4a"
                        level_sfx(f, out)
                        rec.update(category=tags[0], duration_s=duration(out), key=f"library/sfx/{tags[0]}/{tid}.m4a")
                        print(f"+ sfx   {tid}: {tags[0]}, {rec['duration_s']}s")
                        uploads = [(out, rec["key"])]
                    if not dry:
                        for path, key in uploads:
                            storage.upload_file(path, key, "audio/mp4")
                    data[kind].append(rec)
                    known.add(digest)
                    added += 1
    if added and not dry:
        save(data)
    print(f"\n{added} added, {skipped} already in the library{' (dry run: nothing uploaded)' if dry else ''}.")
    summary(data)


def summary(data: dict) -> None:
    from collections import Counter
    moods = Counter(m for t in data["music"] if not t.get("blocked") for m in t["moods"])
    sfx = Counter(s["category"] for s in data["sfx"] if not s.get("blocked"))
    print("music:", dict(moods) or "none", f"({len(data['music'])} tracks)")
    print("sfx:  ", dict(sfx) or "none (built-in pack only)")


def set_blocked(tid: str, blocked: bool) -> None:
    data = load()
    for rec in data["music"] + data["sfx"]:
        if rec["id"] == tid:
            rec["blocked"] = blocked
            save(data)
            print(("blocked " if blocked else "unblocked ") + tid)
            return
    sys.exit(f"no item {tid}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path)
    ap.add_argument("--source", default="pixabay")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--block")
    ap.add_argument("--unblock")
    a = ap.parse_args()
    if a.block or a.unblock:
        set_blocked(a.block or a.unblock, bool(a.block))
    elif a.list:
        data = load()
        for t in data["music"]:
            print(f"{'BLOCKED ' if t.get('blocked') else ''}{t['id']}: {t['moods']} {t['energy']} {t['bpm']} BPM {t['duration_s']}s")
        summary(data)
    elif a.folder:
        if not a.folder.is_dir():
            sys.exit(f"{a.folder} is not a folder")
        import_dir(a.folder, a.source, a.dry_run)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
