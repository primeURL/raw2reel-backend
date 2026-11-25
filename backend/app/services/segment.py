"""Person cut-out: which pixels are the person? For text that sits behind the speaker.

Model: MediaPipe Selfie Segmenter (Google, Apache 2.0), run with LiteRT (ai-edge-litert) -
a 250 KB model and a 16 MB runtime, instead of the full MediaPipe package (which pulls a
second OpenCV, matplotlib and audio libraries).

The raw 256x256 mask is soft and blocky; a guided filter snaps its edge to the real edges
of the picture (hair, shoulders), and a little blending with the previous frame stops flicker.
"""

import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parent.parent / "assets" / "models" / "selfie_segmenter.tflite"
SIZE = 256

_lock = threading.Lock()  # one LiteRT interpreter per process; renders on other threads take turns


@lru_cache(maxsize=1)
def _interpreter():
    from ai_edge_litert.interpreter import Interpreter

    it = Interpreter(model_path=str(MODEL), num_threads=2)
    it.allocate_tensors()
    return it, it.get_input_details()[0]["index"], it.get_output_details()[0]["index"]


def _guided(guide: np.ndarray, src: np.ndarray, r: int = 4, eps: float = 2e-3) -> np.ndarray:
    def box(x):
        return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1))

    mi, mp = box(guide), box(src)
    a = (box(guide * src) - mi * mp) / (box(guide * guide) - mi * mi + eps)
    b = mp - a * mi
    return np.clip(box(a) * guide + box(b), 0, 1)


class PersonMasker:
    """Call with consecutive RGB frames; returns a float32 mask (0 = background, 1 = person)."""

    def __init__(self, w: int, h: int, smooth: float = 0.35):
        self.w, self.h, self.smooth = w, h, smooth
        self.work = (max(2, w // 4), max(2, h // 4))  # edge refinement at quarter size: sharp enough, 4x faster
        self.prev: np.ndarray | None = None

    def reset(self) -> None:
        self.prev = None

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        small = cv2.resize(rgb, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        it, inp, out = _interpreter()
        with _lock:
            it.set_tensor(inp, small[None])
            it.invoke()
            m = it.get_tensor(out)[0, :, :, 0].copy()
        half = cv2.resize(rgb, self.work, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(half, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
        m = cv2.resize(m, self.work, interpolation=cv2.INTER_LINEAR)
        m = _guided(gray, m)
        m = np.clip((m - 0.5) * 1.8 + 0.5, 0, 1)  # firmer edge
        if self.prev is not None:
            m = (1 - self.smooth) * m + self.smooth * self.prev
        self.prev = m
        return cv2.resize(m, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
