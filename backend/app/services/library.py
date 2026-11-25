"""The sound library: music beds and extra sound effects, kept in R2 under library/.

scripts/import_sounds.py adds files (from Pixabay or any source whose licence allows use inside
edited videos): it levels them, works out tempo and beats, uploads them and records each in
library/manifest.json with where it came from. Workers read the manifest and download a file the
first time a render needs it, then keep it on disk.

Pixabay's licence allows its music inside our users' edited reels, but not handing the files
out on their own, so the app only ever streams 20-second previews, never the full track.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

from app import storage
from app.config import get_settings

log = logging.getLogger(__name__)

MANIFEST_KEY = "library/manifest.json"
MOODS = ("upbeat", "energetic", "chill", "lofi", "emotional", "cinematic", "inspiring", "funny", "desi", "dramatic")
MOOD_HELP = {
    "upbeat": "happy, bright, everyday vlogs and food",
    "energetic": "fast, driving: fitness, sport, hype",
    "chill": "relaxed, warm: travel, mornings, slow days",
    "lofi": "soft beats under talking, study, cosy",
    "emotional": "heartfelt, piano or strings: stories, milestones",
    "cinematic": "big, sweeping: reveals, travel, before/after",
    "inspiring": "rising, hopeful: progress, motivation, launches",
    "funny": "quirky, playful: comedy, fails, pets",
    "desi": "Indian sounds: festivals, weddings, desi life",
    "dramatic": "tense, suspense: hooks, plot twists, challenges",
}
# free words in older plans' moods -> library moods
SYNONYMS = {
    "calm": "chill", "relaxed": "chill", "gentle": "chill", "warm": "chill", "travel": "chill", "acoustic": "chill",
    "happy": "upbeat", "feel-good": "upbeat", "bright": "upbeat", "playful": "funny", "quirky": "funny",
    "motivat": "inspiring", "uplift": "inspiring", "hopeful": "inspiring", "builds": "inspiring",
    "hype": "energetic", "workout": "energetic", "fast": "energetic", "driving": "energetic",
    "sad": "emotional", "heartfelt": "emotional", "piano": "emotional", "epic": "cinematic",
    "tense": "dramatic", "suspense": "dramatic", "indian": "desi", "bollywood": "desi", "study": "lofi",
}
TTL_S = 300

_cache: dict = {"at": 0.0, "data": None}


def _empty() -> dict:
    return {"version": 1, "music": [], "sfx": []}


def manifest(fresh: bool = False) -> dict:
    """The library's catalogue (cached for a few minutes; empty if there is none yet)."""
    if not fresh and _cache["data"] is not None and time.time() - _cache["at"] < TTL_S:
        return _cache["data"]
    try:
        data = json.loads(storage.read_bytes(MANIFEST_KEY))
    except storage.StorageNotConfigured:
        data = _empty()
    except Exception as e:  # missing manifest (no library yet) or R2 hiccup: carry on without music
        if "NoSuchKey" not in repr(e) and "404" not in repr(e):
            log.warning("sound library manifest unavailable: %s", e)
        data = _cache["data"] or _empty()
    _cache.update(at=time.time(), data=data)
    return data


def set_manifest(data: dict) -> None:
    """Test hook / import script: use this catalogue instead of reading R2."""
    _cache.update(at=time.time(), data=data)


def music_tracks() -> list[dict]:
    return [t for t in manifest()["music"] if not t.get("blocked")]


def track(track_id: str | None) -> dict | None:
    if not track_id:
        return None
    return next((t for t in music_tracks() if t["id"] == track_id), None)


def moods_available() -> list[str]:
    have = {m for t in music_tracks() for m in t.get("moods", [])}
    return [m for m in MOODS if m in have]


def sfx_files(category: str) -> list[dict]:
    return [s for s in manifest()["sfx"] if s.get("category") == category and not s.get("blocked")]


def sfx_categories() -> set[str]:
    return {s["category"] for s in manifest()["sfx"] if not s.get("blocked")}


def fetch(key: str) -> Path | None:
    """Local copy of a library file (downloaded once)."""
    dest = Path(get_settings().work_dir) / "library" / key
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        tmp = dest.with_suffix(dest.suffix + ".part")
        storage.download_file(key, tmp)
        tmp.replace(dest)
        return dest
    except Exception as e:
        log.warning("couldn't fetch library file %s: %s", key, e)
        return None


def _rank(seed: str, tid: str) -> str:
    return hashlib.sha1(f"{seed}:{tid}".encode()).hexdigest()


def choose_music(mood: str | None, energy: str | None, seed: str, reel_s: float = 30.0,
                 avoid: set[str] | None = None) -> dict | None:
    """A track for this reel: the mood first, then the energy, then one long enough not to loop.
    The seed (the project id) keeps the choice stable across remakes, yet varied between reels."""
    tracks = [t for t in music_tracks() if t["id"] not in (avoid or set())] or music_tracks()
    if not tracks:
        return None
    mood = (mood or "").lower()
    # the AI writes free words ("warm upbeat acoustic"): match any library mood inside them
    wanted = {m for m in MOODS if m in mood} or {m for w, m in SYNONYMS.items() if w in mood}

    def score(t: dict) -> tuple:
        moods = set(t.get("moods", []))
        return (
            -len(wanted & moods),
            0 if not energy or t.get("energy") == energy else 1,
            0 if t.get("duration_s", 0) >= reel_s else 1,
            _rank(seed, t["id"]),
        )

    return min(tracks, key=score)
