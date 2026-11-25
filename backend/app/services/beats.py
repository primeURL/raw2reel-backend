"""Listen to a music track once: its tempo, where the beats fall, how loud and how busy it is.

Plain numpy (no librosa): an onset envelope from spectral flux, tempo from its autocorrelation,
then the beat phase that lands on the most onsets. Good enough to put cuts on the beat; it runs
when a track is added to the library, never during a render.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 22050
HOP = 512  # ~23 ms per envelope step
WIN = 2048
LAG_S = WIN / SR  # a hit shows in the flux about one window before it plays: shift beats back by this
MIN_BPM, MAX_BPM = 70.0, 180.0


@dataclass
class Analysis:
    duration_s: float
    bpm: float | None
    beats: list[float]  # seconds
    lufs: float  # integrated loudness
    energy: str  # calm | medium | high


def decode(path: Path, sr: int = SR) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=300).stdout
    return np.frombuffer(raw, np.float32)


def onset_envelope(x: np.ndarray) -> np.ndarray:
    n = WIN
    if len(x) < n * 2:
        return np.zeros(1)
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::HOP] * np.hanning(n)
    mag = np.log1p(10 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # take away the slow swell
    return np.maximum(flux, 0)


def tempo_and_beats(env: np.ndarray) -> tuple[float | None, list[float]]:
    fps = SR / HOP
    if len(env) < fps * 4 or env.max() <= 0:
        return None, []
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(len(ac))
    lo, hi = int(fps * 60 / MAX_BPM), int(fps * 60 / MIN_BPM)
    # prefer tempos near 110 BPM a little, so half/double tempo don't win on a tie
    bpm_at = 60 * fps / np.maximum(lags[lo:hi + 1], 1)
    weight = np.exp(-0.5 * (np.log2(bpm_at / 110.0) / 0.9) ** 2)
    lag = lo + int(np.argmax(ac[lo:hi + 1] * weight))
    # refine to a fraction of a step around the peak
    if lo < lag < hi:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        lag = lag + (0.5 * (a - c) / den if den else 0)
    period = float(lag)
    # beat phase: the offset whose comb collects the most onset strength
    steps = int(period) + 1
    scores = [env[np.round(np.arange(p, len(env), period)).astype(int).clip(0, len(env) - 1)].sum() for p in range(steps)]
    phase = int(np.argmax(scores))
    # follow the beat, letting each one settle on the strongest onset within a few steps
    beats, t = [], float(phase)
    while t < len(env):
        k = int(round(t))
        w = max(1, int(period * 0.1))
        win = env[max(0, k - w): k + w + 1]
        if win.size and win.max() > 0:
            k = max(0, k - w) + int(np.argmax(win))
        beats.append(k / fps + LAG_S)
        t = k + period
    return round(60 * fps / period, 1), [round(b, 3) for b in beats]


def loudness(path: Path) -> float:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    m = json.loads(p.stderr[p.stderr.rindex("{"): p.stderr.rindex("}") + 1])
    v = m["input_i"]
    return -70.0 if v in ("-inf", "inf") else float(v)


def momentary_max(path: Path) -> float:
    """Loudest 400 ms of a short sound, in LUFS: how sound effects are levelled."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=60)
    vals = [float(v) for v in re.findall(r"M:\s*(-?[\d.]+)", p.stderr)]
    return max(vals) if vals else -70.0


# energy score buckets, set on a 56-track Pixabay set: piano/heartfelt ~0-25, travel/cinematic
# ~30-65, workout/upbeat/dhol ~70+
CALM_ENERGY, HIGH_ENERGY = 30.0, 70.0


def energy_score(x: np.ndarray) -> tuple[float, float]:
    """How busy and bright the music is, whatever its loudness: mean onset strength of the middle
    of the track (levelled first) plus a little for brightness. Returns (score, centroid Hz)."""
    mid = x[int(len(x) * 0.2): int(len(x) * 0.8)]
    if mid.size < WIN * 4:
        return 0.0, 0.0
    mid = mid / (np.sqrt(np.mean(mid ** 2)) + 1e-9) * 0.1
    flux = float(onset_envelope(mid).mean())
    n = min(200, mid.size // WIN)
    spec = np.abs(np.fft.rfft(mid[: n * WIN].reshape(n, WIN) * np.hanning(WIN), axis=1)).mean(axis=0)
    centroid = float((spec * np.fft.rfftfreq(WIN, 1 / SR)).sum() / (spec.sum() + 1e-9))
    return flux + (centroid - 1000) / 50, centroid


def analyse(path: Path) -> Analysis:
    x = decode(path)
    env = onset_envelope(x)
    bpm, beats = tempo_and_beats(env)
    e, _ = energy_score(x)
    energy = "high" if e > HIGH_ENERGY else "medium" if e > CALM_ENERGY else "calm"
    return Analysis(duration_s=round(len(x) / SR, 2), bpm=bpm, beats=beats, lufs=round(loudness(path), 1), energy=energy)


def best_offset(beats: list[float], cuts: list[float], track_s: float, reel_s: float, tol: float = 0.07) -> float:
    """Where in the track to start so the most cuts land on a beat (tie: the earliest start).

    Starts are tried on beats, so the reel opens on one. The track may loop (it is looped in the
    mix), so starts anywhere in it are fine."""
    if not beats or not cuts:
        return 0.0
    arr = np.array(beats)
    best, best_score = 0.0, -1
    for start in beats[: max(1, int(len(beats) * 0.75))]:
        shifted = [((c + start) % track_s) if track_s > 0 else c + start for c in cuts]
        score = sum(1 for s in shifted if np.min(np.abs(arr - s)) <= tol)
        # music that has to loop inside a short reel is worse than one clean run
        if start + reel_s > track_s:
            score -= 0.5
        if score > best_score:
            best, best_score = start, score
    return float(best)
