"""Background music under the edit: pick a track, start it where its beats meet the cuts, and dip
it whenever someone talks.

The library's tracks are levelled to -14 LUFS (scripts/import_sounds.py); the voice is levelled to
-16 LUFS by the renderer, so one gain per volume setting places the music under it. On top of that
a sidechain compressor ducks the music while the voice is speaking and lets it back up in pauses.
"""

from dataclasses import dataclass
from pathlib import Path

from app.services import beats as B
from app.services import library as L
from app.services.plan_schema import EditPlan

# dB on the track's -14 LUFS, before ducking
GAIN_DB = {"low_under_voice": -15.0, "medium": -10.0, "music_led": -6.0}
GAIN_NO_VOICE_DB = -2.0  # nothing to sit under: the music is the sound of the reel (~ -16 LUFS)
FADE_IN_S = 0.4
ENERGY = {"off": "calm", "subtle": "medium", "punchy": "high"}


def cut_times(plan: EditPlan) -> list[float]:
    out, t = [], 0.0
    for sh in plan.shots[:-1]:
        t += max(0.0, (sh.out_s - sh.in_s) / (sh.speed or 1.0))
        out.append(round(t, 3))
    return out


def reel_length(plan: EditPlan) -> float:
    return sum(max(0.0, (s.out_s - s.in_s) / (s.speed or 1.0)) for s in plan.shots)


def assign(plan: EditPlan, seed: str) -> dict | None:
    """Make sure an enabled plan names a library track (keeps the creator's pick if it still exists)."""
    if not plan.music.enabled:
        return None
    t = L.track(plan.music.track)
    if t is None:
        t = L.choose_music(plan.music.mood, ENERGY.get(plan.sound_effects), seed, reel_length(plan))
        plan.music.track = t["id"] if t else None
    return t


@dataclass
class MusicMix:
    inputs: list[str]
    chains: list[str]
    label: str
    title: str
    start_s: float


def mix_graph(plan: EditPlan, total: float, voiced: bool, input_index: int, voice_key: str | None) -> MusicMix | None:
    """ffmpeg inputs and filters for the music. voice_key: a copy of the levelled voice to duck under."""
    t = L.track(plan.music.track) if plan.music.enabled else None
    if t is None:
        return None
    path: Path | None = L.fetch(t["key"])
    if path is None:
        return None
    start = B.best_offset(t.get("beats") or [], cut_times(plan), t.get("duration_s") or 0, total)
    gain = GAIN_DB.get(plan.music.volume, -10.0) if voiced else GAIN_NO_VOICE_DB
    # loop forever from the chosen start; the mix stops at the reel's length
    inputs = ["-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", str(path)]
    chain = (f"[{input_index}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
             f"volume={gain:.1f}dB,afade=t=in:d={FADE_IN_S}")
    chains = []
    if voiced and voice_key:
        chains.append(chain + "[mus_raw]")
        # dip ~8-10 dB under speech, back up within ~0.4 s of a pause
        chains.append(f"[mus_raw][{voice_key}]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=400:knee=4[mus]")
    else:
        chains.append(chain + "[mus]")
    return MusicMix(inputs, chains, "mus", t.get("title", t["id"]), start)
