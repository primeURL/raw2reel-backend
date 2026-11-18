"""Check an edit plan against the real clips and the style, fixing small mistakes in place.

Runs on every plan Claude writes and every plan the user saves - no AI involved, so fixing a
plan costs nothing. Small problems are repaired and reported as warnings; impossible plans
raise PlanError.
"""

import re
from dataclasses import dataclass

from app.services.plan_schema import EditPlan

MIN_SHOT_S = 0.4
MAX_REEL_S = 90.0
MAX_TAIL_S = 6.0  # longest last-frame hold under an end card
TIGHT_ZOOM = 1.4  # zoomed this far in, the subject fills the frame


class PlanError(ValueError):
    pass


@dataclass
class ClipInfo:
    alias: str
    duration_s: float


def readable_s(text: str) -> float:
    """Time needed to read a caption: 0.5 s + 0.3 s per word, at least 1.0 s."""
    return max(1.0, 0.5 + 0.3 * len(text.split()))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


_NUM_UNIT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:km|k|m|min|mins|sec|s|kg|%)?\b", re.I)


def _whole_highlight(text: str, hl: str) -> str | None:
    """The highlight must be a whole word/phrase of the caption. A bare number grows to include
    its unit ('2' in 'Target: 2 km' -> '2 km')."""
    hl = hl.strip()
    if not hl or hl.lower() not in text.lower():
        return None
    for m in _NUM_UNIT.finditer(text):
        if m.group(0).strip().lower().startswith(hl.lower()):
            return m.group(0).strip()
    if not re.search(rf"(?<!\w){re.escape(hl)}(?!\w)", text, re.I):
        return None  # part of a word: drop rather than colour half a word
    return hl


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def validate(plan: EditPlan, clips: dict[str, ClipInfo], style: dict | None = None) -> tuple[EditPlan, list[str], dict]:
    """Returns (fixed plan, warnings, timeline). timeline = per-shot start/end on the reel."""
    warnings: list[str] = []
    captions_style = (style or {}).get("captions") or {}
    max_words = captions_style.get("max_words_on_screen")

    if not plan.shots:
        raise PlanError("The plan has no shots")

    # shots -------------------------------------------------------------------
    kept = []
    for i, s in enumerate(plan.shots, start=1):
        clip = clips.get(s.clip)
        if clip is None:
            warnings.append(f"Shot {i}: unknown clip {s.clip!r}, removed")
            continue
        speed = _clamp(s.speed or 1.0, 0.25, 2.0)
        in_s = _clamp(s.in_s, 0.0, clip.duration_s)
        out_s = _clamp(s.out_s, 0.0, clip.duration_s)
        if (in_s, out_s) != (s.in_s, s.out_s):
            warnings.append(f"Shot {i}: trimmed to the clip's length ({clip.duration_s:.2f}s)")
        if out_s - in_s < MIN_SHOT_S:
            warnings.append(f"Shot {i}: shorter than {MIN_SHOT_S}s, removed")
            continue
        s.in_s, s.out_s, s.speed = round(in_s, 3), round(out_s, 3), round(speed, 3)
        s.zoom_from = round(_clamp(s.zoom_from or 1.0, 1.0, 2.0), 3)
        s.zoom_to = round(_clamp(s.zoom_to or 1.0, 1.0, 2.0), 3)
        s.focus_x = round(_clamp(s.focus_x, 0.0, 1.0), 3)
        s.focus_y = round(_clamp(s.focus_y, 0.0, 1.0), 3)
        kept.append(s)
    if not kept:
        raise PlanError("None of the plan's shots fit the uploaded clips")
    plan.shots = kept

    timeline, t = [], 0.0
    for i, s in enumerate(plan.shots):
        d = (s.out_s - s.in_s) / s.speed
        timeline.append({"shot": i, "clip": s.clip, "start_s": round(t, 3), "end_s": round(t + d, 3)})
        t += d
    total = round(t, 3)
    if total > MAX_REEL_S:
        raise PlanError(f"The reel would be {total:.0f}s long; the maximum is {MAX_REEL_S:.0f}s")

    # end-card tail -------------------------------------------------------------
    # An end card may run past the last shot: the reel then holds the last frame under it.
    footage = total
    tail = 0.0
    for o in plan.overlays:
        if o.end_s > footage and o.start_s >= footage - MAX_TAIL_S:
            tail = max(tail, min(o.end_s - footage, MAX_TAIL_S))
    if tail:
        total = round(footage + tail, 3)
    # captions ------------------------------------------------------------------
    caps = []
    for c in sorted(plan.captions, key=lambda c: c.start_s):
        c.text = " ".join(c.text.split())
        if not c.text:
            continue
        c.start_s = round(_clamp(c.start_s, 0.0, total), 3)
        c.end_s = round(_clamp(c.end_s, 0.0, total), 3)
        if caps and c.start_s < caps[-1].end_s:  # overlap -> start after the previous one
            c.start_s = caps[-1].end_s
            warnings.append(f"Caption {c.text!r}: overlapped the previous caption, moved")
        if c.end_s - c.start_s < 0.3:
            warnings.append(f"Caption {c.text!r}: no time left on screen, removed")
            continue
        if c.end_s - c.start_s < readable_s(c.text) - 0.05:
            warnings.append(f"Caption {c.text!r}: on screen {c.end_s - c.start_s:.1f}s, needs ~{readable_s(c.text):.1f}s to read")
        if max_words and len(c.text.split()) > max_words + 2:
            warnings.append(f"Caption {c.text!r}: {len(c.text.split())} words, style allows {max_words}")
        if c.highlight:
            c.highlight = _whole_highlight(c.text, c.highlight)
        caps.append(c)
    plan.captions = caps
    if sum(1 for c in caps if c.highlight) > 1 and (style or {}).get("look", {}).get("accent_color"):
        for c in caps[1:]:
            if c.highlight and any(p.highlight for p in caps[: caps.index(c)]):
                c.highlight = None
        warnings.append("More than one highlighted word; kept only the first (style: one accent at most)")

    # overlays -----------------------------------------------------------------
    ovs = []
    for o in sorted(plan.overlays, key=lambda o: o.start_s):
        o.start_s = round(_clamp(o.start_s, 0.0, total), 3)
        o.end_s = round(_clamp(o.end_s, 0.0, total), 3)
        if o.end_s - o.start_s < 0.5:
            warnings.append(f"Overlay {o.type}: too short, removed")
            continue
        if ovs and o.start_s < ovs[-1].end_s:
            warnings.append(f"Overlay {o.type}: overlapped another overlay, removed")
            continue
        o.items = o.items[:6]
        ovs.append(o)
    plan.overlays = ovs

    # captions over a tight shot: the subject fills the middle/lower frame, so use the sky --
    for c in plan.captions:
        if c.position == "upper_third":
            continue
        mid = (c.start_s + c.end_s) / 2
        shot_at = next((t for t in timeline if t["start_s"] <= mid < t["end_s"]), None)
        if shot_at and max(plan.shots[shot_at["shot"]].zoom_from, plan.shots[shot_at["shot"]].zoom_to) >= TIGHT_ZOOM:
            c.position = "upper_third"
            warnings.append(f"Caption {c.text!r}: moved to the upper third (tight shot, would cover the subject)")

    # captions vs overlays: never on top of a card, never repeat a title -------------
    for o in ovs:
        during = [c for c in plan.captions if c.start_s < o.end_s and c.end_s > o.start_s]
        if o.type == "stats_card":
            for c in during:
                if c.position != "lower_middle":
                    c.position = "lower_middle"
                    warnings.append(f"Caption {c.text!r}: moved below the stats card")
        elif o.type == "title" and o.title:
            t = _norm(o.title)
            for c in during:
                if _norm(c.text) and (_norm(c.text) in t or t in _norm(c.text)):
                    warnings.append(f"Title {o.title!r} repeats caption {c.text!r} at the same time")

    plan.end_fade_s = round(_clamp(plan.end_fade_s, 0.0, 1.5), 2)

    return plan, warnings, {"total_s": total, "footage_s": footage, "tail_hold_s": round(tail, 3), "shots": timeline}
