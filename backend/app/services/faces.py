"""Where is the face? YuNet (OpenCV, MIT) on a few frames a second, smoothed into a track.

Used by the renderer, on the joined reel itself (so zooms and crops are already applied):
  - effects zoom into / light up / point at the face
  - captions are moved when they would cover it

A track is a list of (cx, cy, w) in output pixels per sample, or None when no face was seen.
"""

import logging
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL = Path(__file__).resolve().parent.parent / "assets" / "models" / "yunet.onnx"
SAMPLE_FPS = 5
DETECT_W = 288  # detection runs on a small copy: plenty for faces bigger than ~4% of the frame


class FaceTrack:
    """Face position over time on the reel, interpolated between samples."""

    def __init__(self, samples: list[tuple[float, float, float] | None], fps: float, scale: float):
        self.fps = fps
        self.found = sum(1 for s in samples if s is not None)
        self._arr = _smooth(samples, fps)  # Nx3 in detection pixels, or None
        self._seen = _near_seen(samples, fps)
        self._scale = scale

    def at(self, t: float) -> tuple[float, float, float] | None:
        """(cx, cy, face width) in output pixels at reel time t, or None if no face anywhere near."""
        if self._arr is None:
            return None
        i = t * self.fps
        lo = int(max(0, min(len(self._arr) - 1, math.floor(i))))
        hi = min(len(self._arr) - 1, lo + 1)
        if not (self._seen[lo] or self._seen[hi]):
            return None
        f = i - lo
        cx, cy, w = self._arr[lo] * (1 - f) + self._arr[hi] * f
        return cx * self._scale, cy * self._scale, w * self._scale

    def boxes(self, start: float, end: float, step: float = 0.2) -> list[tuple[float, float, float]]:
        out, t = [], start
        while t <= end + 1e-6:
            f = self.at(t)
            if f is not None:
                out.append(f)
            t += step
        return out


@lru_cache(maxsize=4)
def _detector(w: int, h: int):
    import cv2

    return cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.6, 0.3, 20)


def track(video: Path, out_w: int, out_h: int, duration_s: float, fps: int = SAMPLE_FPS) -> FaceTrack:
    """Detect faces on `fps` frames per second of `video` (out_w x out_h on screen)."""
    dw = DETECT_W
    dh = int(round(dw * out_h / out_w / 2)) * 2
    scale = out_w / dw
    samples: list[tuple[float, float, float] | None] = []
    try:
        import cv2

        det = _detector(dw, dh)
        p = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf", f"fps={fps},scale={dw}:{dh},format=bgr24",
             "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE,
        )
        n = dw * dh * 3
        try:
            while True:
                b = p.stdout.read(n)
                if len(b) < n:
                    break
                frame = np.frombuffer(b, np.uint8).reshape(dh, dw, 3)
                _, faces = det.detect(frame)
                if faces is not None and len(faces):
                    r = max(faces, key=lambda r: r[2] * r[3] * r[-1])  # biggest, most confident
                    samples.append((float(r[0] + r[2] / 2), float(r[1] + r[3] / 2), float(r[2])))
                else:
                    samples.append(None)
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()
            p.wait()
    except Exception:  # face tracking improves the edit; it must never break a render
        log.warning("face tracking failed for %s", video, exc_info=True)
        samples = []
    ft = FaceTrack(samples, fps, scale)
    log.info("faces: %d of %d samples (%.1fs)", ft.found, len(samples), duration_s)
    return ft


def _near_seen(samples: list, fps: float, hold_s: float = 0.6) -> list[bool]:
    """A sample counts as 'has a face' if one was detected within hold_s (detector blinks)."""
    k = max(1, int(round(hold_s * fps)))
    hits = [s is not None for s in samples]
    return [any(hits[max(0, i - k): i + k + 1]) for i in range(len(hits))] or [False]


def _smooth(samples: list, fps: float, tau: float = 0.25):
    """Fill gaps by interpolation, then a forward + backward pass so the smoothing has no lag."""
    idx = [i for i, s in enumerate(samples) if s is not None]
    if not idx:
        return None
    arr = np.array([s if s is not None else (np.nan,) * 3 for s in samples], np.float64)
    for k in range(3):
        col = arr[:, k]
        good = ~np.isnan(col)
        col[~good] = np.interp(np.where(~good)[0], np.where(good)[0], col[good])
    a = 1 - math.exp(-1 / (fps * tau))
    for i in range(1, len(arr)):
        arr[i] = arr[i - 1] + a * (arr[i] - arr[i - 1])
    for i in range(len(arr) - 2, -1, -1):
        arr[i] = arr[i + 1] + a * (arr[i] - arr[i + 1])
    return arr


def keep_out(face: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """The head area text must not cover: hair to just under the chin, a little wider than the face.
    (YuNet's box is about 1.2x as tall as wide, centred between the eyes and the mouth.)"""
    cx, cy, w = face
    return cx - 0.7 * w, cy - 1.0 * w, cx + 0.7 * w, cy + 0.75 * w
