"""Repeated movement in a clip: push-ups, squats, curls, skipping... counted without any AI.

The person cut-out model (segment.py) gives, for each frame, where the body's weight sits in
the picture. During an exercise that point goes down and up once per rep, so the reps are the
peaks of that curve. A peak has to stand out from the clip's own wobble (prominence), and two
peaks need a little time between them, so a shaky phone or someone walking past isn't counted.

Result (stored in the clip's analysis as "reps"):
  {"count": 9, "down_s": [1.5, 4.5, ...], "up_s": [3.1, 6.2, ...], "period_s": 3.0}
down_s = the bottom of each rep, up_s = when it's finished (back up). Times inside the clip.
"""

import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

FPS = 10
W, H = 144, 256
MIN_REPS = 3
MIN_GAP_S = 0.5     # faster than this isn't a rep (skipping counts ~2 per second, so keep it low)
MIN_AREA = 0.02
AFTER_REP_S = 0.3   # a shot ending on a rep runs this much past it
MAX_STRETCH_S = 1.5  # a cut moves at most this much to take in a whole rep; past that, the half rep is dropped     # the model lost the person in this frame: fill it in from its neighbours


def body_curve(src: Path, fps: int = FPS) -> np.ndarray:
    """Height of the body's centre in the frame, 0 = top, 1 = bottom, at `fps` samples a second
    (NaN where no person was found)."""
    from app.services import segment as SG

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={fps},scale={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=600).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    it, inp, out = SG._interpreter()
    rows = (np.arange(SG.SIZE, dtype=np.float32) / SG.SIZE)[:, None]
    ys = np.full(len(frames), np.nan, np.float32)
    for k, f in enumerate(frames):
        small = cv2.resize(f, (SG.SIZE, SG.SIZE), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        with SG._lock:
            it.set_tensor(inp, small[None])
            it.invoke()
            m = it.get_tensor(out)[0, :, :, 0]
        area = float(m.mean())
        if area >= MIN_AREA:
            ys[k] = float((m * rows).sum() / (m.sum() + 1e-6))
    return ys


def _smooth(y: np.ndarray, sigma: float) -> np.ndarray:
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(y, r, mode="edge"), k, mode="valid")


def _prominence(y: np.ndarray, i: int) -> float:
    """How far peak i rises above the lower of the two valleys around it (each side ends at a higher point)."""
    left = i
    lo_l = y[i]
    while left > 0 and y[left - 1] <= y[i]:
        left -= 1
        lo_l = min(lo_l, y[left])
    right = i
    lo_r = y[i]
    while right < len(y) - 1 and y[right + 1] <= y[i]:
        right += 1
        lo_r = min(lo_r, y[right])
    return float(y[i] - max(lo_l, lo_r))


def find_reps(curve: np.ndarray, fps: int = FPS) -> dict | None:
    """Reps from a body curve, or None when there's no clear repeated movement."""
    y = np.asarray(curve, np.float64)
    ok = ~np.isnan(y)
    if ok.sum() < fps * 3:
        return None
    t = np.arange(len(y))
    y = np.interp(t, t[ok], y[ok])
    seen = np.convolve(ok.astype(float), np.ones(2 * int(0.3 * fps) + 1), mode="same") > int(0.3 * fps)  # person found around here
    y = _smooth(y, sigma=0.2 * fps)
    spread = float(np.percentile(y, 95) - np.percentile(y, 5))
    if spread < 0.03:  # the body barely moves up and down
        return None
    need = max(0.025, 0.35 * spread)
    cands = [i for i in range(1, len(y) - 1)
             if y[i] >= y[i - 1] and y[i] > y[i + 1] and seen[i] and _prominence(y, i) >= need]
    kept: list[int] = []
    for i in sorted(cands, key=lambda i: -y[i]):  # highest first; drop near-duplicates of a kept peak
        if all(abs(i - j) >= MIN_GAP_S * fps for j in kept):
            kept.append(i)
    kept.sort()
    downs, ups = [], []
    for n, i in enumerate(kept):  # a rep is only done once the body is back up: most of the way to where it started
        end = kept[n + 1] if n + 1 < len(kept) else len(y)
        back = y[i] - 0.6 * _prominence(y, i)
        up = next((j for j in range(i + 1, end) if y[j] <= back and seen[j]), None)
        if up is not None:
            downs.append(i)
            ups.append(up)
    kept = downs
    if len(kept) < MIN_REPS:
        return None
    gaps = np.diff(kept) / fps
    return {
        "count": len(kept),
        "down_s": [round(i / fps, 2) for i in kept],
        "up_s": [round(i / fps, 2) for i in ups],
        "period_s": round(float(np.median(gaps)), 2),
    }


def detect(src: Path) -> dict | None:
    try:
        return find_reps(body_curve(src))
    except Exception:
        log.exception("rep detection failed for %s", src)
        return None


def in_range(reps: dict | None, start: float, end: float) -> list[float]:
    """Finish times of the reps that happen fully inside [start, end] of the clip."""
    if not reps:
        return []
    return [u for d, u in zip(reps["down_s"], reps["up_s"]) if start <= d and u <= end + 0.15]


def windows(reps: dict | None) -> list[tuple[float, float]]:
    """Each rep from its start (at the top, going down) to its finish (back up), in clip seconds.
    Going down takes about as long as coming back up."""
    if not reps:
        return []
    out, prev_up = [], 0.0
    for d, u in zip(reps["down_s"], reps["up_s"]):
        out.append((round(max(prev_up, d - (u - d)), 2), u))
        prev_up = u
    return out


def snap_cut(t: float, reps: dict | None, side: str) -> float:
    """Move a cut that lands inside a rep to the rep's edge, so the rep is shown whole: a shot
    starting mid-rep starts at its beginning, one ending mid-rep (or right as it finishes) ends a
    moment after it's finished, so the count going up is seen. When that would add more than
    MAX_STRETCH_S, the half rep is left out instead (start after it / end before it)."""
    for a, b in windows(reps):
        if side == "in" and a + 0.05 < t < b - 0.05:
            return a if t - a <= MAX_STRETCH_S else b
        if side == "out" and a + 0.05 < t < b + AFTER_REP_S:
            end = round(b + AFTER_REP_S, 2)
            return end if end - t <= MAX_STRETCH_S else a
    return t
