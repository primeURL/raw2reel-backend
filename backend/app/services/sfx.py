"""Sound effects under the edit: each visual effect gets its sound, timed to the moment it lands.

The sounds are a small pack rendered once with earshot (scripts/make_sfx_pack.py; MIT, the
renders are ours to use commercially). Each file is levelled to the same loudness, so one gain
per mode places them under the voice, which the renderer levels to -16 LUFS.
"""

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.services import library
from app.services.plan_schema import EditPlan

SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "sfx"
TAKES = 3
# dB on the pack's level (momentary max -14 LUFS): subtle sits clearly under a -16 LUFS voice
GAIN_DB = {"subtle": -9.0, "punchy": -4.0}
MIN_CAPTION_GAP_S = 1.5  # punchy: at most one caption pop this often


@dataclass
class Cue:
    name: str  # pack sound, e.g. "whoosh_fast"
    at_s: float  # reel time its hit should land on
    gain_db: float = 0.0  # on top of the mode's gain


LEVEL_DB = {"soft": -5.0, "normal": 0.0, "loud": 3.0}
# motion graphics: (sound, seconds after it starts; negative = that fraction of its length, e.g. the follow tap)
MOTION_SOUND = {
    "chat": ("pop", 0.15), "counter": ("whoosh_soft", 0.1), "graph": ("whoosh_soft", 0.2), "widgets": ("pop", 0.1),
    "checklist": ("click", 0.5), "progress": ("whoosh_soft", 0.3), "location": ("slam", 0.4), "name_card": ("swipe", 0.0),
    "follow": ("click", -0.5), "emoji_burst": ("pop", 0.1), "poll": ("click", 0.15), "timer": ("tick", 0.0),
    "notification": ("ding", 0.1), "price_tag": ("cash", 0.35),
}


def transition_times(plan: EditPlan) -> list[tuple[float, str]]:
    """(reel time of the cut, kind) for every shot that comes in with a non-cut transition."""
    out, t = [], 0.0
    for sh in plan.shots:
        if sh.transition_in != "cut" and t > 0:
            out.append((t, sh.transition_in))
        t += max(0.0, (sh.out_s - sh.in_s) / (sh.speed or 1.0))
    return out


def _motion_cue(e) -> Cue:
    name, at = MOTION_SOUND[e.type]
    return Cue(name, round(e.start_s + (at * (e.end_s - e.start_s) if at < 0 else at), 3), -3)


def cues(plan: EditPlan, total_s: float) -> list[Cue]:
    """Every sound cue of the reel, minus the sounds the creator has banned (their lessons)."""
    from app.services.lessons import banned

    avoid = getattr(plan, "avoid_sounds", None) or []
    return [c for c in _cues(plan, total_s) if not banned(c.name, avoid)]


def _cues(plan: EditPlan, total_s: float) -> list[Cue]:
    mode = plan.sound_effects
    if mode == "off":
        return []
    if plan.sounds:  # the editor's own sound design, plus each graphic's own sound unless one is already there
        out = [Cue(c.sound, c.at_s, LEVEL_DB.get(c.level, 0.0)) for c in plan.sounds if 0 <= c.at_s < total_s]
        for e in plan.effects:
            if e.type in MOTION_SOUND:
                c = _motion_cue(e)
                if c.at_s < total_s and all(abs(o.at_s - c.at_s) > 0.4 for o in out):
                    out.append(c)
        return sorted(out, key=lambda c: c.at_s)
    # older plans, or none given: sounds follow the effects and transitions
    out: list[Cue] = [Cue("slam" if kind == "flash" else "whoosh_fast", t) for t, kind in transition_times(plan)]
    for e in plan.effects:
        d = e.end_s - e.start_s
        if e.type == "punch_in":
            out.append(Cue("whoosh_fast", e.start_s + 0.06))
        elif e.type == "slow_push":
            out.append(Cue("whoosh_soft", e.start_s + 0.2, -3))
        elif e.type == "spotlight":
            out.append(Cue("boom", e.start_s + 0.1))
        elif e.type == "freeze_frame":
            out.append(Cue("shutter", e.start_s))
        elif e.type == "flash":
            out.append(Cue("slam", e.start_s + d / 2))
        elif e.type == "backdrop_word":
            out.append(Cue("slam", e.start_s + 0.25))  # the word finishes dropping in
        elif e.type == "countdown":
            out += [Cue("tick", e.start_s + k * d / 3) for k in range(3)]
        elif e.type in MOTION_SOUND:
            out.append(_motion_cue(e))
    if mode == "punchy":
        last = -9.0
        for c in plan.captions:
            if c.start_s - last >= MIN_CAPTION_GAP_S:
                out.append(Cue("pop", c.start_s, -5))
                last = c.start_s
    return sorted((c for c in out if 0 <= c.at_s < total_s), key=lambda c: c.at_s)


def sound_pool(name: str) -> list[Path]:
    """Every take of a sound: the built-in pack's, then the library's (small files, downloaded once)."""
    built = [p for k in range(1, TAKES + 1) if (p := SFX_DIR / f"{name}_{k}.ogg").exists()]
    extra = [p for e in library.sfx_files(name) if (p := library.fetch(e["key"])) is not None]
    return built + extra


@lru_cache(maxsize=64)
def hit_offset(path: Path) -> float:
    """Seconds from the file's start to its first strong moment (the part that should land on the beat)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                         capture_output=True, timeout=30).stdout
    a = np.abs(np.frombuffer(raw, np.float32))
    if not a.size:
        return 0.0
    return float(np.argmax(a >= 0.5 * a.max()) / 48000)


def mix_graph(cues_: list[Cue], mode: str, first_input: int) -> tuple[list[str], list[str], list[str]]:
    """ffmpeg -i args, filter chains and output labels for the cues (inputs start at first_input)."""
    inputs, chains, labels = [], [], []
    used: dict[str, int] = {}
    for k, c in enumerate(cues_):
        pool = sound_pool(c.name)
        if not pool:
            continue
        path = pool[used.get(c.name, 0) % len(pool)]  # rotate takes so repeats don't sound copied
        used[c.name] = used.get(c.name, 0) + 1
        if not path.exists():
            continue
        delay_ms = max(0, round((c.at_s - hit_offset(path)) * 1000))
        idx = first_input + len(inputs) // 2
        inputs += ["-i", str(path)]
        label = f"sfx{k}"
        chains.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"volume={GAIN_DB.get(mode, -9.0) + c.gain_db:.1f}dB,adelay={delay_ms}:all=1[{label}]")
        labels.append(label)
    return inputs, chains, labels
