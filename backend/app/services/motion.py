"""Motion-graphics effects: chat bubbles, counters, graphs, glass widgets... drawn as HTML/CSS
animations and rendered frame by frame in headless Chromium with a transparent background.

Each effect is one file in app/assets/motion/<type>.html, built on _base.js:
  - the page is laid out at 1080x1920 CSS px (the reel at full size) with a transparent body;
  - window.FX holds the effect's inputs (title, items, numbers, unit, accent, duration, position);
  - fxBuild(FX), if the page defines it, builds the DOM from them;
  - everything moves with CSS animations, which we pause and seek to each frame's time, so a
    frame is the same every render and doesn't depend on how fast the machine is.

The frames are RGBA PNGs at the reel's size; effects.apply lays them over the picture (or behind
the person) in the same pass as the other effects.
"""

import json
import os
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "motion"
W, H = 1080, 1920
MOTION_TYPES = ("chat", "counter", "graph", "widgets", "checklist", "progress", "location", "name_card",
                "follow", "emoji_burst", "poll", "timer", "notification", "price_tag")

# for the app's effect gallery: name, what it's for, and sample inputs (also used for its preview clip)
CATALOG = {
    "chat": ("💬 Chat", "Messages pop in one by one", {"text": "Gym bro", "items": ["Did you finish?", "Me: 100 push-ups done 💪", "Rahul: no way 😳"]}),
    "counter": ("🔢 Counter", "A big number counts up", {"text": "Push-ups", "numbers": [0, 100]}),
    "graph": ("📊 Graph", "Bars rise to your numbers", {"text": "Weekly km", "items": ["Mon", "Tue", "Wed", "Thu"], "numbers": [3, 5, 4, 8], "unit": "km"}),
    "widgets": ("🧊 Glass widgets", "Up to 4 stat cards pop in", {"items": ["🔥|Calories|120", "⏱️|Time|20 min", "💪|Reps|100", "❤️|Heart|142 bpm"]}),
    "checklist": ("✅ Checklist", "Items tick off one by one", {"text": "Breakfast", "items": ["Oats", "Milk", "Banana"]}),
    "progress": ("📈 Progress", "A bar fills: day 12 of 30", {"text": "Day", "numbers": [12, 30]}),
    "location": ("📍 Location", "A pin drops on a place", {"text": "Pune", "items": ["Maharashtra"]}),
    "name_card": ("🪪 Name card", "Your name and role slide in", {"text": "Utkarsh", "items": ["Founder, Raw2Reel"]}),
    "follow": ("➕ Follow", "A follow button gets tapped", {"text": "@raw2reel"}),
    "emoji_burst": ("🎉 Emoji burst", "Emojis float up", {"items": ["🔥", "💪", "❤️"]}),
    "poll": ("🗳️ Poll", "A question with answer bars", {"text": "Oats or poha?", "items": ["Oats", "Poha"], "numbers": [64, 36]}),
    "timer": ("⏱️ Timer", "A clock ring runs down", {"text": "Plank", "numbers": [60]}),
    "notification": ("🔔 Notification", "A phone notification drops in", {"text": "Mom", "items": ["Did you eat breakfast? 🍳"]}),
    "price_tag": ("🏷️ Price tag", "A price sticker spins in", {"text": "SALE", "numbers": [499, 999], "unit": "₹"}),
}

DEFAULT_POSITION = {"name_card": "bottom", "notification": "top", "follow": "bottom", "emoji_burst": "bottom"}

ZONES = {"top": (0.13, 0.40), "middle": (0.34, 0.66), "bottom": (0.41, 0.67)}  # roughly where .stage sits (_base.css)

_lock = threading.Lock()  # one browser per process; renders on other threads take turns


class MotionError(RuntimeError):
    pass


@dataclass
class Frames:
    folder: Path
    count: int
    fps: int

    def at(self, lt: float) -> Path:
        k = min(self.count - 1, max(0, int(round(lt * self.fps))))
        return self.folder / f"{k:04d}.png"


def inputs(e, accent: str) -> dict:
    """What a template gets from an Effect."""
    return {
        "title": e.text or "", "items": list(e.items or []), "numbers": list(e.numbers or []), "unit": e.unit or "",
        "position": e.position or DEFAULT_POSITION.get(e.type, "top"), "accent": accent, "duration": round(e.end_s - e.start_s, 3),
        "ticks": [round(t - e.start_s, 3) for t in (getattr(e, "ticks_s", None) or [])],  # counter: one up at each
    }


class Browser:
    """One headless Chromium for a batch of effects (launching costs ~1 s)."""

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - image without Chromium
            raise MotionError("motion effects need Playwright + Chromium in the image") from exc
        _lock.acquire()
        try:
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None,
                                                   args=["--disable-gpu", "--font-render-hinting=none", "--disable-lcd-text"])
        except Exception as exc:
            _lock.release()
            raise MotionError(f"couldn't start Chromium: {exc}") from exc
        return self

    def __exit__(self, *exc):
        try:
            self.browser.close()
            self.pw.stop()
        finally:
            _lock.release()

    def render(self, kind: str, fx: dict, w: int, h: int, fps: int, out: Path) -> Frames:
        """One effect's frames (RGBA PNG, w x h) into out/0000.png..."""
        page_file = ASSETS / f"{kind}.html"
        if kind not in MOTION_TYPES or not page_file.exists():
            raise MotionError(f"no motion template for {kind}")
        out.mkdir(parents=True, exist_ok=True)
        n = max(1, int(round(fx["duration"] * fps)))
        page = self.browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=w / W)
        try:
            page.add_init_script(f"window.FX = {json.dumps(fx, ensure_ascii=False)};")
            page.goto(page_file.as_uri())
            page.wait_for_function("window.fxReady === true", timeout=10_000)
            for k in range(n):
                page.evaluate(f"fxSeek({k / fps:.4f})")
                page.screenshot(path=str(out / f"{k:04d}.png"), omit_background=True, type="png")
        except Exception as exc:
            raise MotionError(f"rendering {kind} failed: {exc}") from exc
        finally:
            page.close()
        return Frames(out, n, fps)


def render(kind: str, fx: dict, w: int, h: int, fps: int, out: Path) -> Frames:
    with Browser() as b:
        return b.render(kind, fx, w, h, fps, out)


def render_all(effects: list, w: int, h: int, fps: int, accent: str, work: Path,
               on=lambda f: None) -> dict[int, Frames]:
    """Frames for every motion effect in the plan, keyed by id() of the Effect. A failed one is
    skipped (logged): the reel still renders without it."""
    todo = [(i, e) for i, e in enumerate(effects) if e.type in MOTION_TYPES]
    out: dict[int, Frames] = {}
    if not todo:
        return out
    try:
        with Browser() as b:
            for k, (i, e) in enumerate(todo):
                folder = work / f"motion{i:02d}"
                try:
                    out[id(e)] = b.render(e.type, inputs(e, accent), w, h, fps, folder)
                except MotionError:
                    log.exception("motion effect %s skipped", e.type)
                    shutil.rmtree(folder, ignore_errors=True)
                on((k + 1) / len(todo))
    except MotionError:
        log.exception("motion effects skipped")
    return out


def keep_off_face(effects: list, faces, h: int, notes: list[str]) -> None:
    """A graphic in front of the person must not cover their face: move it to a spot clear of the
    face over its whole time on screen, or, when there's none, draw it behind them."""
    if not getattr(faces, "found", 0):
        return
    for e in effects:
        if e.type not in MOTION_TYPES or e.behind:
            continue
        boxes = faces.boxes(e.start_s, e.end_s, 0.25)
        if not boxes:
            continue
        top = min(cy - 0.6 * fw for _, cy, fw in boxes) / h
        bottom = max(cy + 0.6 * fw for _, cy, fw in boxes) / h

        def covers(zone: str) -> bool:
            lo, hi = ZONES[zone]
            return min(hi, bottom) - max(lo, top) > 0.3 * (bottom - top)

        spot = e.position or DEFAULT_POSITION.get(e.type, "top")
        if not covers(spot):
            continue
        free = next((z for z in ("top", "bottom", "middle") if z != spot and not covers(z)), None)
        name = e.type.replace("_", " ")
        if free:
            e.position = free
            notes.append(f"Graphic {name} moved to the {free} so it doesn't cover your face")
        else:
            e.behind = True
            notes.append(f"Graphic {name} drawn behind you so it doesn't cover your face")
