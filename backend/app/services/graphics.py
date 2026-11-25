"""Captions, titles and the stats card, drawn as full-frame transparent PNGs (1080x1920).

FFmpeg then overlays them with fades. Drawing in Pillow (not ffmpeg drawtext) gives soft
shadows, one highlighted word in the accent colour, wrapping, and per-glyph font fallback
(Inter -> Noto Devanagari -> symbols), so "Day 1 ✓ Kal phir" and Hindi both render.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
SAFE_LEFT, SAFE_RIGHT = 130, 950  # keep clear of the app's right-hand button rail
SAFE_BOTTOM = 1330  # nothing readable below this (caption, handle, buttons)
SAFE_TOP = 230  # the app's top bar (Reels / Following, camera)

INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
FALLBACKS = [
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
WEIGHTS = {"regular": "Regular", "medium": "Medium", "bold": "Bold", "heavy": "ExtraBold"}
SIZES = {"small": 46, "medium": 58, "large": 72}
CENTER_Y = {"upper_third": 560, "middle": 960, "lower_middle": 1150}


@lru_cache
def _cmap(path: str) -> frozenset[int]:
    with TTFont(path, fontNumber=0, lazy=True) as f:
        return frozenset(f.getBestCmap() or {})


@lru_cache
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _font_for(ch: str, primary: str, extra: tuple[str, ...] = ()) -> str:
    if ord(ch) in _cmap(primary) or ch.isspace():
        return primary
    for p in (*extra, *FALLBACKS):
        if ord(ch) in _cmap(p):
            return p
    return primary


@dataclass
class Run:
    text: str
    font: ImageFont.FreeTypeFont
    color: tuple
    word: int = 0  # which word of the caption it belongs to (typewriter reveals words in order)
    hl: bool = False  # part of the highlighted word(s)


def _width(runs: list[Run]) -> float:
    return sum(r.font.getlength(r.text) for r in runs)


def _hex(c: str, alpha: int = 255) -> tuple:
    c = (c or "#FFFFFF").lstrip("#")
    if len(c) != 6:
        c = "FFFFFF"
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)


def _lines(text: str, highlight: str | None, primary: str, size: int, color: tuple, accent: tuple, max_w: int,
           extra: tuple[str, ...] = (), hl_word: int | None = None) -> list[list[Run]]:
    """Word-wrap into lines of runs. Characters inside the highlight phrase use the accent colour
    (hl_word instead: that whole word, for karaoke)."""
    hl_start = hl_end = -1
    if hl_word is None and highlight and highlight.lower() in text.lower():
        hl_start = text.lower().index(highlight.lower())
        hl_end = hl_start + len(highlight)

    space = _font(primary, size).getlength(" ")
    lines: list[list[Run]] = [[]]
    line_w = 0.0
    pos = 0
    for wi, word in enumerate(text.split()):
        start = text.index(word, pos)
        pos = start + len(word)
        runs: list[Run] = []
        for k, ch in enumerate(word):
            hl = wi == hl_word if hl_word is not None else hl_start <= start + k < hl_end
            c = accent if hl else color
            path = _font_for(ch, primary, extra)
            if runs and runs[-1].font.path == path and runs[-1].color == c:
                runs[-1].text += ch
            else:
                runs.append(Run(ch, _font(path, size), c, wi, hl))
        w = _width(runs)
        if lines[-1] and line_w + space + w > max_w:
            lines.append([])
            line_w = 0.0
        if lines[-1]:
            lines[-1].append(Run(" ", _font(primary, size), color, wi))
            line_w += space
        lines[-1].extend(runs)
        line_w += w
    return [ln for ln in lines if ln]


def _balanced(text, highlight, primary, size, color, accent, max_w, extra=(), hl_word=None) -> list[list[Run]]:
    """Wrap, then shrink the line width until the line count would grow: lines come out
    roughly equal ("First, a warm-up / to open up my legs.") instead of leaving one orphan word."""
    lines = _lines(text, highlight, primary, size, color, accent, max_w, extra, hl_word)
    if len(lines) < 2:
        return lines
    widest = max(_width(ln) for ln in lines)
    best, w = lines, widest
    while w > max_w * 0.35:
        w -= 12
        trial = _lines(text, highlight, primary, size, color, accent, int(w), extra, hl_word)
        if len(trial) > len(lines):
            break
        best = trial
    return best


def _draw_block(img: Image.Image, lines: list[list[Run]], center_y: int, size: int, line_gap: float = 1.32,
                shadow: int = 18, letter_spacing: float = 0.0, visible_words: int | None = None) -> tuple[int, int]:
    """visible_words: draw only the first N words, leaving the others' space empty (typewriter)."""
    line_h = int(size * line_gap)
    block_h = line_h * len(lines)
    top = int(center_y - block_h / 2)
    if top + block_h > SAFE_BOTTOM:  # never into the bottom button area
        top = SAFE_BOTTOM - block_h
    text_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td, sd = ImageDraw.Draw(text_layer), ImageDraw.Draw(shadow_layer)
    for i, runs in enumerate(lines):
        total_w = _width(runs) + letter_spacing * max(sum(len(r.text) for r in runs) - 1, 0)
        x = (SAFE_LEFT + SAFE_RIGHT) / 2 - total_w / 2
        y = top + i * line_h
        for r in runs:
            if letter_spacing:
                for ch in r.text:
                    sd.text((x, y + 2), ch, font=r.font, fill=(0, 0, 0, 200))
                    td.text((x, y), ch, font=r.font, fill=r.color)
                    x += r.font.getlength(ch) + letter_spacing
            else:
                if visible_words is None or r.word < visible_words:
                    sd.text((x, y + 2), r.text, font=r.font, fill=(0, 0, 0, 210))
                    td.text((x, y), r.text, font=r.font, fill=r.color)
                x += r.font.getlength(r.text)
    if shadow:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow / 3))
        img.alpha_composite(shadow_layer)
        img.alpha_composite(shadow_layer)  # twice = denser, still soft
    img.alpha_composite(text_layer)
    return top, top + block_h


# public ------------------------------------------------------------------------


SIZE_SCALE = {"small": 0.85, "medium": 1.0, "large": 1.2}
DEFAULT_SIZES = SIZES  # captions without a look keep the original sizes


def caption_png(text: str, dest: Path, *, position: str, size: str = "small", weight: str = "medium",
                color: str = "#FFFFFF", accent: str = "#FF5A1F", highlight: str | None = None,
                case: str = "sentence", center_y: int | None = None, visible_words: int | None = None,
                look=None, active_word: int | None = None) -> Path:
    """center_y overrides the position's height (the renderer uses it to dodge a face).
    visible_words: only the first N words (typewriter steps), laid out exactly like the full caption.
    look: a caption_looks.Look (font, outline, boxes...); without one, the plain Inter caption.
    active_word: karaoke - this word is the highlighted one, whatever `highlight` says."""
    if look is not None and look.case:
        case = look.case
    if case == "upper":
        text, highlight = text.upper(), (highlight.upper() if highlight else None)
    elif case == "lower":
        text, highlight = text.lower(), (highlight.lower() if highlight else None)
    if look is None:
        px = SIZES.get(size, 46)
        primary = INTER.format(WEIGHTS.get(weight, "Medium"))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        lines = _balanced(text, highlight, primary, px, _hex(color), _hex(accent), SAFE_RIGHT - SAFE_LEFT - 40, hl_word=active_word)
        _draw_block(img, lines, center_y or CENTER_Y.get(position, 1150), px, visible_words=visible_words)
        img.save(dest)
        return dest
    px = round(look.size * SIZE_SCALE.get(size, 0.85))
    acc = _hex(look.accent or accent)
    if look.highlight == "none" and active_word is None:
        highlight = None
    base = _hex(look.color)
    hl_color = _hex(look.highlight_text) if look.highlight == "box" and look.highlight_text else (base if look.highlight in ("marker", "underline") else acc)
    pad = 60 if look.background != "none" or look.outline else 40
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lines = _balanced(text, highlight, look.font_path(), px, base, hl_color, SAFE_RIGHT - SAFE_LEFT - pad,
                      look.fallback_paths(), active_word)
    _draw_look(img, lines, center_y or CENTER_Y.get(position, 1150), px, look, acc, visible_words, _hex(accent))
    img.save(dest)
    return dest


def _draw_look(img: Image.Image, lines: list[list[Run]], center_y: int, size: int, look, accent: tuple,
               visible_words: int | None, style_accent: tuple | None = None) -> tuple[int, int]:
    """Draw a caption in a look: background, highlight marks, shadow/glow, outlined text."""
    line_h = int(size * look.line_gap)
    block_h = line_h * len(lines)
    top = int(center_y - block_h / 2)
    if top + block_h > SAFE_BOTTOM:
        top = SAFE_BOTTOM - block_h
    top = max(top, SAFE_TOP)
    ls = look.letter_spacing
    stroke = look.outline

    def run_w(r: Run) -> float:
        return r.font.getlength(r.text) + ls * len(r.text)

    bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    marks = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    text = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd, md, sd, td = (ImageDraw.Draw(x) for x in (bg, marks, shade, text))
    bg_rgb = (style_accent or accent)[:3] if look.background_color == "accent" else _hex(look.background_color)[:3]
    bg_fill = (*bg_rgb, look.background_alpha)
    off = max(3, round(size * 0.06))
    glow = (*accent[:3], 255)
    band = [10**6, 10**6, -1, -1]
    for i, runs in enumerate(lines):
        total_w = sum(run_w(r) for r in runs) - ls
        x = (SAFE_LEFT + SAFE_RIGHT) / 2 - total_w / 2
        y = top + i * line_h
        # glyph box of the line (cap height to descender), from its first font
        f0 = runs[0].font
        gb = f0.getbbox("Hg")
        y0, y1 = y + gb[1], y + gb[3]
        shown_x0 = shown_x1 = None
        hl_spans: list[list[float]] = []
        for r in runs:
            w = run_w(r)
            visible = visible_words is None or r.word < visible_words
            if visible and r.text.strip():
                shown_x0 = x if shown_x0 is None else shown_x0
                shown_x1 = x + w - ls
            if visible and r.hl and r.text.strip():
                if hl_spans and abs(hl_spans[-1][1] - x) < size * 0.4:
                    hl_spans[-1][1] = x + w - ls  # same word or next highlighted word: one mark
                else:
                    hl_spans.append([x, x + w - ls])
            if visible:
                cx = x
                for ch in (r.text if ls else [r.text]):
                    if look.shadow == "soft":
                        sd.text((cx, y + 2), ch, font=r.font, fill=(0, 0, 0, 210), stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
                    elif look.shadow == "hard":
                        sd.text((cx + off, y + off), ch, font=r.font, fill=(0, 0, 0, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
                    elif look.shadow == "glow":
                        sd.text((cx, y), ch, font=r.font, fill=glow, stroke_width=max(stroke, 3), stroke_fill=glow)
                    # text on a highlight box needs no outline (it would smear into the box)
                    st = 0 if (r.hl and look.highlight == "box") else stroke
                    td.text((cx, y), ch, font=r.font, fill=r.color, stroke_width=st, stroke_fill=_hex(look.outline_color))
                    cx += r.font.getlength(ch) + ls if ls else 0
            x += w
        if shown_x0 is None:
            continue
        px_, py_ = size * 0.32, size * 0.16
        if look.background == "box":
            bd.rounded_rectangle([shown_x0 - px_, y0 - py_, shown_x1 + px_, y1 + py_], radius=look.radius, fill=bg_fill)
        elif look.background == "band":
            band = [min(band[0], shown_x0), min(band[1], y0), max(band[2], shown_x1), max(band[3], y1)]
        for x0_, x1_ in hl_spans:
            if look.highlight == "box":
                md.rounded_rectangle([x0_ - size * 0.16, y0 - size * 0.08, x1_ + size * 0.16, y1 + size * 0.06],
                                     radius=max(6, look.radius // 2), fill=(*accent[:3], 255))
            elif look.highlight == "marker":
                md.rectangle([x0_ - size * 0.08, y0 + (y1 - y0) * 0.45, x1_ + size * 0.08, y1 - (y1 - y0) * 0.02],
                             fill=(*accent[:3], 190))
            elif look.highlight == "underline":
                t_ = max(4, round(size * 0.08))
                md.rectangle([x0_, y1 - t_ * 0.2, x1_, y1 + t_ * 0.8], fill=(*accent[:3], 255))
    if look.background == "band" and band[2] > 0:
        bd.rounded_rectangle([band[0] - size * 0.45, band[1] - size * 0.3, band[2] + size * 0.45, band[3] + size * 0.3],
                             radius=look.radius, fill=bg_fill)
    img.alpha_composite(bg)
    if look.shadow == "soft":
        shade = shade.filter(ImageFilter.GaussianBlur(6))
        img.alpha_composite(shade)
        img.alpha_composite(shade)
    elif look.shadow == "glow":
        shade = shade.filter(ImageFilter.GaussianBlur(max(8, size // 6)))
        img.alpha_composite(shade)
        img.alpha_composite(shade)
    elif look.shadow == "hard":
        img.alpha_composite(shade)
    img.alpha_composite(marks)
    img.alpha_composite(text)
    return top, top + block_h


def layer_center_y(png: Path) -> int:
    """Vertical centre of what's drawn on a caption layer (to redraw it at the same height)."""
    box = Image.open(png).getchannel("A").getbbox()
    return int((box[1] + box[3]) / 2) if box else CENTER_Y["lower_middle"]


def title_png(text: str, dest: Path, *, color: str = "#FFFFFF") -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    primary = INTER.format("SemiBold")
    lines = _lines(text, None, primary, 64, _hex(color), _hex(color), SAFE_RIGHT - SAFE_LEFT)
    _draw_block(img, lines, 520, 64, letter_spacing=4)
    img.save(dest)
    return dest


def stats_card_png(title: str | None, items: list[tuple[str, str]], dest: Path, *, accent: str = "#FF5A1F",
                   color: str = "#FFFFFF") -> Path:
    """Dimmed frame + heading + first stat big in the accent colour + the rest in one line +
    a simple route line. Laid out like the hand-made Day 1 card."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * 0.62)))
    white, acc = _hex(color), _hex(accent)
    y = 470
    if title:
        lines = _lines(title.upper(), None, INTER.format("Medium"), 40, white, white, 900)
        _, y = _draw_block(img, lines, y, 40, letter_spacing=12, shadow=8)
    if items:
        big = _lines(items[0][1], None, INTER.format("Bold"), 160, acc, acc, 900)
        _, y = _draw_block(img, big, y + 20 + 105, 160, line_gap=1.1, shadow=12)
        rest = "  ·  ".join(v for _, v in items[1:])
        if rest:
            lines = _lines(rest, None, INTER.format("Medium"), 52, white, white, 900)
            _, y = _draw_block(img, lines, y + 20 + 34, 52, shadow=8)
    # route: start dot (white) -> line -> finish dot (accent)
    d = ImageDraw.Draw(img)
    cx, y0, y1 = (SAFE_LEFT + SAFE_RIGHT) // 2, y + 230, y + 70
    if y0 < SAFE_BOTTOM - 120:
        d.line([(cx, y0), (cx, y1)], fill=acc, width=8)
        d.ellipse([cx - 12, y0 - 12, cx + 12, y0 + 12], fill=white)
        d.ellipse([cx - 12, y1 - 12, cx + 12, y1 + 12], fill=acc)
    img.save(dest)
    return dest


def text_sprite(text: str, size: int, *, weight: str = "ExtraBold", color: str = "#FFFFFF", shadow: int = 18,
                max_w: int = 900) -> Image.Image:
    """Text cut tight to its pixels (with shadow), for effects that move or scale it."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    primary = INTER.format(weight)
    lines = _lines(text, None, primary, size, _hex(color), _hex(color), max_w)
    _draw_block(img, lines, H // 2, size, shadow=shadow)
    box = img.getchannel("A").getbbox()
    return img.crop(box) if box else img.crop((0, 0, 1, 1))
