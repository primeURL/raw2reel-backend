"""Face-aware effects, frame by frame, on the joined reel (ideas from the MIT-licensed
claude-video-effects; rewritten for our pipeline with fast OpenCV ops).

Only frames inside an effect window are touched; the rest pass straight through. Audio is
copied, so a freeze_frame stills the picture while the voice keeps going.

  punch_in      quick zoom onto the face, held, quick release
  slow_push     slow push in towards the face
  spotlight     everything but the person goes dark
  grade         a colour look (moody, bw, warm, cool, pop), eased in and out
  freeze_frame  the picture holds, a label and a drawn arrow point at the person
  flash         a white flash
  countdown     a big 3-2-1 above the person
  backdrop_word a giant word drops in BEHIND the person (person cut-out, see segment.py)
"""

import logging
import math
import subprocess
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.services import graphics
from app.services.faces import FaceTrack
from app.services.plan_schema import Effect
from app.services.motion import MOTION_TYPES
from app.services.segment import PersonMasker

log = logging.getLogger(__name__)


class EffectsError(RuntimeError):
    pass


def _clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def _ease_out(x: float) -> float:
    x = _clamp(x)
    return 1 - (1 - x) ** 3


def _ease_inout(x: float) -> float:
    x = _clamp(x)
    return 3 * x * x - 2 * x * x * x


def _ramp(lt: float, d: float, t_in: float, t_out: float) -> float:
    """0 -> 1 over t_in at the start, 1 -> 0 over t_out at the end."""
    a = _clamp(lt / t_in) if t_in else 1.0
    b = _clamp((d - lt) / t_out) if t_out else 1.0
    return min(a, b)


# looks -------------------------------------------------------------------------------


def _curve(gain: float = 1.0, lift: float = 0.0, contrast: float = 1.0) -> np.ndarray:
    x = np.arange(256, dtype=np.float32) / 255.0
    x = (x - 0.5) * contrast + 0.5
    x = x * gain + lift / 255.0
    return (np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)


# (R, G, B) curves + saturation
LOOKS = {
    "moody": ((_curve(0.96, 4, 1.12), _curve(0.95, 2, 1.12), _curve(0.98, 10, 1.08)), 0.7),
    "bw": (None, 0.0),
    "warm": ((_curve(1.05, 8, 1.03), _curve(1.0, 3, 1.03), _curve(0.9, 0, 1.03)), 1.05),
    "cool": ((_curve(0.92, 0, 1.03), _curve(0.99, 3, 1.03), _curve(1.06, 10, 1.03)), 0.95),
    "pop": ((_curve(1.0, 0, 1.1), _curve(1.0, 0, 1.1), _curve(1.0, 0, 1.1)), 1.35),
}


def _saturate(img: np.ndarray, s: float) -> np.ndarray:
    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
    if s == 0:
        return gray
    return cv2.addWeighted(img, s, gray, 1 - s, 0)


def _grade(img: np.ndarray, look: str) -> np.ndarray:
    curves, sat = LOOKS.get(look, LOOKS["moody"])
    if look == "bw":
        g = _saturate(img, 0.0)
        return cv2.LUT(g, _curve(1.0, 0, 1.15))
    out = img
    if sat != 1.0:
        out = _saturate(out, sat)
    if curves is not None:
        r, g, b = cv2.split(out)
        out = cv2.merge((cv2.LUT(r, curves[0]), cv2.LUT(g, curves[1]), cv2.LUT(b, curves[2])))
    return out


# helpers -----------------------------------------------------------------------------


def _zoom(img: np.ndarray, z: float, cx: float, cy: float) -> np.ndarray:
    """Zoom in by z, keeping the face around 40% from the top, never showing past the edges."""
    if z <= 1.001:
        return img
    h, w = img.shape[:2]
    cw, ch = w / z, h / z
    x0 = _clamp(cx - cw / 2, 0, w - cw)
    y0 = _clamp(cy - ch * 0.4, 0, h - ch)
    m = np.float32([[z, 0, -x0 * z], [0, z, -y0 * z]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _paste(img: np.ndarray, sprite: np.ndarray, x: int, y: int, alpha: float = 1.0) -> None:
    """Alpha-composite an RGBA sprite onto img (in place), clipped to the frame."""
    if alpha <= 0:
        return
    h, w = img.shape[:2]
    sh, sw = sprite.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + sw), min(h, y + sh)
    if x0 >= x1 or y0 >= y1:
        return
    s = sprite[y0 - y: y1 - y, x0 - x: x1 - x]
    a = (s[:, :, 3:4].astype(np.float32) / 255.0) * alpha
    region = img[y0:y1, x0:x1].astype(np.float32)
    img[y0:y1, x0:x1] = (region * (1 - a) + s[:, :, :3].astype(np.float32) * a + 0.5).astype(np.uint8)


def _sprite(im: Image.Image, scale: float) -> np.ndarray:
    if abs(scale - 1) > 0.01:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    return np.asarray(im.convert("RGBA"))


class _Renderer:
    def __init__(self, effects: list[Effect], faces: FaceTrack, w: int, h: int, fps: int, accent: str,
                 motion_frames: dict | None = None):
        self.fx, self.faces, self.w, self.h, self.fps = effects, faces, w, h, fps
        self.motion_frames = motion_frames or {}
        self.k = w / graphics.W  # sprites are designed at 1080 wide
        self.accent = accent
        self.cache: dict = {}
        self.masker: PersonMasker | None = None
        self.mask_t = -1.0

    def face(self, t: float) -> tuple[float, float, float]:
        return self.faces.at(t) or (self.w / 2, self.h * 0.36, self.w * 0.2)

    def steady_face(self, e: Effect) -> tuple[float, float, float]:
        """Average face over the effect, so zooms aim at one spot instead of wobbling."""
        key = ("steady", id(e))
        if key not in self.cache:
            boxes = self.faces.boxes(e.start_s, e.end_s, 0.1)
            self.cache[key] = tuple(np.mean(boxes, axis=0)) if boxes else self.face(e.start_s)
        return self.cache[key]

    # per frame
    def frame(self, img: np.ndarray, t: float, active: list[Effect]) -> np.ndarray:
        order = {"freeze_frame": 0, "punch_in": 1, "slow_push": 1, "grade": 2, "backdrop_word": 3, "spotlight": 4,
                 "countdown": 5, "flash": 7}
        for e in sorted(active, key=lambda e: order.get(e.type, 6)):  # motion graphics: under the flash
            lt, d = t - e.start_s, max(e.end_s - e.start_s, 0.05)
            img = (self.motion if e.type in MOTION_TYPES else getattr(self, e.type))(img, e, lt, d, t)
        return img

    def motion(self, img, e, lt, d, t):
        """A motion graphic's frame (pre-rendered RGBA) over the picture, or behind the person."""
        frames = self.motion_frames.get(id(e))
        if frames is None:
            return img
        layer = cv2.imread(str(frames.at(lt)), cv2.IMREAD_UNCHANGED)
        if layer is None or layer.ndim != 3 or layer.shape[2] != 4:
            return img
        if layer.shape[:2] != (self.h, self.w):
            layer = cv2.resize(layer, (self.w, self.h), interpolation=cv2.INTER_AREA)
        a = layer[:, :, 3:4].astype(np.float32) / 255.0
        if not a.any():
            return img
        rgb = layer[:, :, 2::-1].astype(np.float32)  # BGRA -> RGB
        out = img.astype(np.float32) * (1 - a) + rgb * a
        if e.behind:
            m = self.person_mask(img, t)[:, :, None]
            out = out * (1 - m) + img.astype(np.float32) * m
        return (out + 0.5).astype(np.uint8)

    def punch_in(self, img, e, lt, d, t):
        cx, cy, fw = self.steady_face(e)
        z = 1 + 0.35 * _ease_out(lt / 0.14) * (1 - _ease_inout((lt - (d - 0.12)) / 0.12))
        return _zoom(img, z, cx, cy)

    def slow_push(self, img, e, lt, d, t):
        cx, cy, fw = self.steady_face(e)
        return _zoom(img, 1 + 0.16 * _ease_inout(lt / d), cx, cy)

    def grade(self, img, e, lt, d, t):
        a = _ramp(lt, d, 0.3, 0.3)
        graded = _grade(img, e.look or "moody")
        return graded if a >= 0.999 else cv2.addWeighted(graded, a, img, 1 - a, 0)

    def spotlight(self, img, e, lt, d, t):
        a = _ramp(lt, d, 0.25, 0.25)
        cx, cy, fw = self.face(t)
        small = 4
        sh, sw = self.h // small, self.w // small
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        # head-and-shoulders ellipse, soft edge
        ex, ey = (xx * small - cx) / (fw * 1.3), (yy * small - (cy + fw * 0.6)) / (fw * 2.0)
        m = np.clip(1.45 - np.sqrt(ex * ex + ey * ey), 0, 1)
        m = cv2.resize(m, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        dark = 0.2
        factor = (1 - a * (1 - dark) * (1 - m))[:, :, None]
        return (img.astype(np.float32) * factor + 0.5).astype(np.uint8)

    def flash(self, img, e, lt, d, t):
        a = 0.9 * (1 - abs(2 * lt / d - 1))
        return cv2.addWeighted(img, 1 - a, np.full_like(img, 255), a, 0)

    def countdown(self, img, e, lt, d, t):
        step = d / 3
        n = min(2, int(lt // step))
        num = str(3 - n)
        key = ("num", num)
        if key not in self.cache:
            color = self.accent if num == "1" else "#FFFFFF"
            self.cache[key] = graphics.text_sprite(num, 420, color=color, shadow=30)
        local = lt - n * step
        pop = 1.3 - 0.3 * _ease_out(local / 0.18)
        alpha = _clamp(local / 0.06) * _clamp((step - local) / 0.1)
        spr = _sprite(self.cache[key], self.k * pop)
        cx, cy, fw = self.face(t)
        y = max(self.h * 0.12, cy - fw * 1.9 - spr.shape[0] / 2) if self.faces.at(t) else self.h * 0.3 - spr.shape[0] / 2
        _paste(img, spr, int(cx - spr.shape[1] / 2), int(y), alpha)
        return img

    def person_mask(self, img: np.ndarray, t: float) -> np.ndarray:
        if self.masker is None:
            self.masker = PersonMasker(self.w, self.h)
        if t - self.mask_t > 1.5 / self.fps:  # a gap since the last masked frame: no stale smoothing
            self.masker.reset()
        self.mask_t = t
        return self.masker(img)

    def backdrop_word(self, img, e, lt, d, t):
        """Giant word behind the person: draw it on the frame, then put the person back on top."""
        key = ("word", id(e))
        if key not in self.cache:
            word = (e.text or "").upper()
            spr = graphics.text_sprite(word, 300, color="#FFFFFF", shadow=24, max_w=1000)
            fit = min(self.w * 0.94 / spr.width, self.h * 0.3 / spr.height)
            self.cache[key] = _sprite(spr, fit)
            cx, cy, fw = self.steady_face(e)
            self.cache[("word_at", id(e))] = (cx, cy, fw, self.faces.at(e.start_s) is not None)
        spr = self.cache[key]
        cx, cy, fw, has_face = self.cache[("word_at", id(e))]
        a = _ramp(lt, d, 0.3, 0.25)
        drop = (1 - _ease_out(lt / 0.35)) * self.h * 0.04
        sh, sw = spr.shape[:2]
        # only the word's lower part tucks behind the hair, so it stays readable
        centre_y = max(self.h * 0.12 + sh / 2, cy - fw * 0.8 - sh * 0.3) if has_face else self.h * 0.3
        x, y = int(self.w / 2 - sw / 2), int(centre_y - sh / 2 - drop)
        mask = self.person_mask(img, t)
        back = cv2.convertScaleAbs(img, alpha=1 - 0.25 * a)  # dim the room a little so the word reads
        _paste(back, spr, x, y, a)
        return cv2.blendLinear(img, back, mask, 1 - mask)  # person on top, word behind

    def freeze_frame(self, img, e, lt, d, t):
        key = ("freeze", id(e))
        if key not in self.cache:  # first frame of the window: keep it, draw the label once
            self.cache[key] = (img.copy(), self._freeze_overlay(e, self.face(e.start_s)))
        still, (spr, x, y) = self.cache[key]
        out = still.copy()
        _paste(out, spr, x, y, _clamp(lt / 0.15))
        if lt < 0.08:  # shutter blink
            out = cv2.addWeighted(out, 0.4, np.full_like(out, 255), 0.6, 0)
        return out

    def _freeze_overlay(self, e: Effect, face) -> tuple[np.ndarray, int, int]:
        """Label pill + a hand-drawn arrow from it to the person, as one full-frame sprite."""
        cx, cy, fw = face
        k = self.k
        canvas = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        label = graphics.text_sprite(e.text or "Look", 64, color="#FFFFFF", shadow=0, max_w=760)
        label = label.resize((max(1, int(label.width * k)), max(1, int(label.height * k))), Image.LANCZOS)
        pad_x, pad_y = int(34 * k), int(20 * k)
        pw, ph = label.width + 2 * pad_x, label.height + 2 * pad_y
        top_room = cy - fw * 1.2
        above = top_room > ph + self.h * 0.14
        px = int(_clamp(cx - pw / 2, self.w * 0.08, self.w * 0.92 - pw))
        py = int(self.h * 0.13) if above else int(min(cy + fw * 1.6, self.h * 0.62))
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle([px, py, px + pw, py + ph], radius=int(ph / 2), fill=graphics._hex(self.accent))
        canvas.alpha_composite(label, (px + pad_x, py + pad_y))
        # arrow: from the pill's edge, bowing out, to just beside the face
        sx, sy = px + pw * 0.5, (py + ph + 10 * k) if above else (py - 10 * k)
        tx = cx + (fw * 0.8 if sx >= cx else -fw * 0.8)
        ty = cy - fw * 0.2 if above else cy + fw * 0.7
        length = math.hypot(tx - sx, ty - sy) or 1
        bx, by = (sx + tx) / 2 - (ty - sy) / length * length * 0.22, (sy + ty) / 2 + (tx - sx) / length * length * 0.22
        pts = [((1 - u) ** 2 * sx + 2 * (1 - u) * u * bx + u * u * tx, (1 - u) ** 2 * sy + 2 * (1 - u) * u * by + u * u * ty)
               for u in (i / 30 for i in range(31))]
        width = max(3, int(9 * k))
        d.line(pts, fill=(255, 255, 255, 255), width=width, joint="curve")
        ang = math.atan2(pts[-1][1] - pts[-4][1], pts[-1][0] - pts[-4][0])
        head = 34 * k
        for da in (2.6, -2.6):
            d.line([pts[-1], (pts[-1][0] + head * math.cos(ang + da), pts[-1][1] + head * math.sin(ang + da))],
                   fill=(255, 255, 255, 255), width=width)
        return np.asarray(canvas), 0, 0


TRANSITION_HALF_S = 0.14  # a transition spans this long either side of the cut


def transition(img: np.ndarray, kind: str, p: float) -> np.ndarray:
    """p: -1 .. 0 (the cut) .. 1. The outgoing shot leaves before 0, the incoming one arrives after."""
    h, w = img.shape[:2]
    k = 1 - abs(p)  # 1 at the cut
    if kind == "whip":  # fast sideways pan with motion blur: out to the left, in from the right
        dx = -0.22 * w * _ease_inout(1 + p) if p < 0 else 0.22 * w * _ease_inout(1 - p)
        m = np.float32([[1, 0, dx], [0, 1, 0]])
        img = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        blur = int(3 + 90 * k * k)
        return cv2.blur(img, (blur, 1)) if blur > 3 else img
    if kind == "zoom":  # zoom in through the cut, a little blur at the peak
        img = _zoom(img, 1 + 0.4 * k * k, w / 2, h * 0.4)
        blur = int(1 + 16 * k * k)
        return cv2.blur(img, (blur, blur)) if blur > 2 else img
    if kind == "flash":
        a = 0.9 * k * k
        return cv2.addWeighted(img, 1 - a, np.full_like(img, 255), a, 0)
    return img


def apply(src: Path, dest: Path, effects: list[Effect], faces: FaceTrack, w: int, h: int, fps: int, accent: str,
          total_s: float, on: Callable[[float], None] = lambda _: None, crf: int = 16,
          transitions: list[tuple[float, str]] = (), motion_frames: dict | None = None) -> Path:
    """src (w x h, fps) -> dest with the effects and transitions drawn in. Audio is copied untouched.
    transitions: (reel time of the cut, kind) - see transition().
    motion_frames: id(effect) -> motion.Frames for the motion graphics (motion.render_all)."""
    r = _Renderer(effects, faces, w, h, fps, accent, motion_frames)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", "-i", str(src), "-map", "0:v", "-map", "1:a?",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                            "-c:a", "copy", "-shortest", str(dest)],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n = w * h * 3
    end = max(total_s, 0.1)
    i = 0
    try:
        while True:
            b = dec.stdout.read(n)
            if len(b) < n:
                break
            t = i / fps
            active = [e for e in effects if e.start_s <= t < e.end_s]
            cut = next(((c, kind) for c, kind in transitions if abs(t - c) < TRANSITION_HALF_S), None)
            if active or cut:
                img = np.frombuffer(b, np.uint8).reshape(h, w, 3).copy()
                if active:
                    img = r.frame(img, t, active)
                if cut:
                    img = transition(img, cut[1], (t - cut[0]) / TRANSITION_HALF_S)
                b = np.ascontiguousarray(img).tobytes()
            enc.stdin.write(b)
            if i % fps == 0:
                on(min(1.0, t / end))
            i += 1
        enc.stdin.close()
        enc.wait(timeout=300)
    except BrokenPipeError as exc:
        raise EffectsError(f"encoder stopped: {enc.stderr.read().decode(errors='ignore')[-400:]}") from exc
    finally:
        for p in (dec, enc):
            if p.poll() is None:
                p.kill()
        dec.stdout.close()
    if enc.returncode != 0:
        raise EffectsError(f"encoding effects failed: {enc.stderr.read().decode(errors='ignore')[-400:]}")
    return dest
