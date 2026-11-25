"""Check an edit plan against the real clips and the style, fixing small mistakes in place.

Runs on every plan Claude writes and every plan the user saves - no AI involved, so fixing a
plan costs nothing. Small problems are repaired and reported as warnings; impossible plans
raise PlanError.
"""

import re
from dataclasses import dataclass, field

from app.services import library, reps
from app.services.motion import MOTION_TYPES
from app.services.plan_schema import BUILT_IN_SOUNDS, EditPlan, SoundCue

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
    words: list[tuple[float, float]] = field(default_factory=list)  # spoken words (start, end) in the clip
    reps: dict | None = None  # repeated movement found in the clip (services/reps.py), for counters

    @classmethod
    def of(cls, alias: str, duration_s: float, analysis: dict | None) -> "ClipInfo":
        return cls(alias, duration_s, clip_words(analysis), (analysis or {}).get("reps"))


def clip_words(analysis: dict | None) -> list[tuple[float, float]]:
    """Word timings from a clip's analysis, for cutting between words instead of through them."""
    segs = ((analysis or {}).get("transcript") or {}).get("segments") or []
    return [(w["start"], w["end"]) for s in segs for w in s.get("words") or [] if w.get("end", 0) > w.get("start", 0)]


WORD_PAD_IN, WORD_PAD_OUT = 0.06, 0.12  # breathing room before the first and after the last word


def _snap_cut(t: float, words: list[tuple[float, float]], side: str) -> float:
    """If a cut lands inside a spoken word, move it to just before (in) / after (out) that word."""
    for ws, we in words:
        if ws < t < we:
            return ws - WORD_PAD_IN if side == "in" else we + WORD_PAD_OUT
    return t


# Effects: (shortest, longest) seconds, and which ones move the picture (never two at once)
EFFECT_LIMITS = {
    "punch_in": (0.4, 3.0), "slow_push": (1.5, 8.0), "spotlight": (0.8, 5.0), "grade": (0.5, MAX_REEL_S),
    "freeze_frame": (0.6, 3.0), "flash": (0.1, 0.6), "countdown": (1.2, 4.0), "backdrop_word": (1.0, 5.0),
    **{k: (1.5, 8.0) for k in MOTION_TYPES}, "counter": (1.5, 20.0),  # a rep counter can run through a whole set
}
MAX_ITEMS, MAX_ITEM_CHARS, MAX_NUMBERS = 6, 70, 8
MIN_SOUND_GAP_S = 0.25
MAX_SOUNDS = 30
TEXT_FX = {"freeze_frame": 40, "backdrop_word": 16, **{k: 50 for k in MOTION_TYPES}}  # effects that carry text: max characters
REP_TICK = "rep counted"  # the why of the app's own counter ticks
CAMERA_FX = {"punch_in", "slow_push", "freeze_frame"}


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
    asked = [(s.in_s, s.out_s, max(0.05, s.speed or 1.0)) for s in plan.shots]  # the cuts as written, for re-timing
    kept, kept_idx = [], []
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
        if s.keep_audio and clip.words:
            new_in = _clamp(_snap_cut(in_s, clip.words, "in"), 0.0, clip.duration_s)
            new_out = _clamp(_snap_cut(out_s, clip.words, "out"), 0.0, clip.duration_s)
            if (new_in, new_out) != (in_s, out_s):
                warnings.append(f"Shot {i}: cut moved so it doesn't chop a word")
                in_s, out_s = new_in, new_out
        elif clip.reps:
            new_in, new_out = reps.snap_cut(in_s, clip.reps, "in"), _clamp(reps.snap_cut(out_s, clip.reps, "out"), 0.0, clip.duration_s)
            if (new_in, new_out) != (in_s, out_s):
                warnings.append(f"Shot {i}: cut moved so each rep is shown whole, down and up")
                in_s, out_s = new_in, new_out
        if out_s - in_s < MIN_SHOT_S and (s.in_s, s.out_s) != (in_s, out_s) and s.out_s - s.in_s >= MIN_SHOT_S:
            in_s, out_s = s.in_s, s.out_s  # moving the cuts left nothing: keep them as written
        if out_s - in_s < MIN_SHOT_S:
            warnings.append(f"Shot {i}: shorter than {MIN_SHOT_S}s, removed")
            continue
        s.in_s, s.out_s, s.speed = round(in_s, 3), round(out_s, 3), round(speed, 3)
        s.zoom_from = round(_clamp(s.zoom_from or 1.0, 1.0, 2.0), 3)
        s.zoom_to = round(_clamp(s.zoom_to or 1.0, 1.0, 2.0), 3)
        s.focus_x = round(_clamp(s.focus_x, 0.0, 1.0), 3)
        s.focus_y = round(_clamp(s.focus_y, 0.0, 1.0), 3)
        kept.append(s)
        kept_idx.append(i - 1)
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
    _retime(plan, asked, kept_idx, total)

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
    keyword_style = bool((style or {}).get("captions", {}).get("keyword_highlight"))
    if sum(1 for c in caps if c.highlight) > 1 and not keyword_style and (style or {}).get("look", {}).get("accent_color"):
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

    # effects ---------------------------------------------------------------------
    fxs, camera_until = [], -1.0
    for e in sorted(plan.effects, key=lambda e: e.start_s):
        lo, hi = EFFECT_LIMITS.get(e.type, (0.3, 5.0))
        name = e.type.replace("_", " ")
        e.start_s = round(_clamp(e.start_s, 0.0, footage), 3)  # effects work on footage, not the held tail
        e.end_s = round(_clamp(e.end_s, 0.0, footage), 3)
        if e.end_s - e.start_s < lo:
            if e.start_s + lo <= footage:
                e.end_s = round(e.start_s + lo, 3)
                warnings.append(f"Effect {name} at {e.start_s:.1f}s: too short, lengthened to {lo:.1f}s")
            else:
                warnings.append(f"Effect {name} at {e.start_s:.1f}s: no room before the end, removed")
                continue
        if e.end_s - e.start_s > hi:
            e.end_s = round(e.start_s + hi, 3)
            warnings.append(f"Effect {name} at {e.start_s:.1f}s: shortened to {hi:.1f}s")
        if e.type in CAMERA_FX:
            if e.start_s < camera_until:
                warnings.append(f"Effect {name} at {e.start_s:.1f}s: overlaps another zoom/freeze, removed")
                continue
            camera_until = e.end_s
        if e.type == "grade" and not e.look:
            e.look = "moody"
        if e.type != "grade":
            e.look = None
        e.text = (" ".join((e.text or "").split())[: TEXT_FX[e.type]] or None) if e.type in TEXT_FX else None
        if e.type == "backdrop_word" and not e.text:
            warnings.append(f"Effect {name} at {e.start_s:.1f}s: no word to show, removed")
            continue
        e.ticks_s = []
        if e.type == "counter":
            _sync_counter(e, plan.shots, timeline, clips, footage)
        if e.type in MOTION_TYPES:
            e.items = [" ".join(str(x).split())[:MAX_ITEM_CHARS] for x in e.items if str(x).strip()][:MAX_ITEMS]
            e.numbers = [float(x) for x in e.numbers][:MAX_NUMBERS]
            e.unit = (e.unit or "").strip()[:8] or None
            _clear_of_captions(e, plan.captions, warnings)
            clash = next((f for f in fxs if f.type in MOTION_TYPES and (f.position or "top") == (e.position or "top")
                          and f.start_s < e.end_s and e.start_s < f.end_s), None)
            if clash:
                warnings.append(f"Effect {name} at {e.start_s:.1f}s: overlaps the {clash.type.replace('_', ' ')} in the same spot, removed")
                continue
        else:
            e.items, e.numbers, e.unit, e.position, e.behind = [], [], None, None, False
        fxs.append(e)
    plan.effects = fxs

    # transitions: the first shot just starts; no fancy transition inside one continuous take -------
    for i, sh in enumerate(plan.shots):
        prev = plan.shots[i - 1] if i else None
        continuous = prev is not None and prev.clip == sh.clip and abs(prev.out_s - sh.in_s) < 0.05
        if sh.transition_in != "cut" and (i == 0 or continuous):
            sh.transition_in = "cut"

    # sounds: on the reel, in time order, not piled on top of each other ------------------------
    if plan.sound_effects == "off":
        plan.sounds = []
    plan.sounds = [c for c in plan.sounds if not (c.sound == "tick" and c.why == REP_TICK)]  # re-made below
    if plan.sound_effects != "off":  # a soft tick each time the counter goes up
        for e in plan.effects:
            if e.ticks_s:
                plan.sounds = [c for c in plan.sounds if all(abs(c.at_s - t) > 0.3 for t in e.ticks_s)] + [
                    SoundCue(sound="tick", at_s=t, level="soft", why=REP_TICK) for t in e.ticks_s]
    snds = []
    for c in sorted(plan.sounds, key=lambda c: c.at_s):
        if c.sound not in BUILT_IN_SOUNDS and c.sound not in library.sfx_categories():
            warnings.append(f"Sound {c.sound} at {c.at_s:.1f}s: not in the sound library yet, removed")
            continue
        if not 0 <= c.at_s < total:
            warnings.append(f"Sound {c.sound} at {c.at_s:.1f}s: outside the reel, removed")
            continue
        if snds and c.at_s - snds[-1].at_s < MIN_SOUND_GAP_S:
            continue  # too close to the previous one: they'd blur into one
        c.at_s = round(c.at_s, 3)
        snds.append(c)
    plan.sounds = snds[:MAX_SOUNDS]

    plan.end_fade_s = round(_clamp(plan.end_fade_s, 0.0, 1.5), 2)

    used = {s.clip for s in plan.shots}
    unused = [a for a in clips if a not in used]
    for a in unused:
        warnings.append(f"Clip {a} isn't used in this edit - add it in the editor if you want it")

    return plan, warnings, {"total_s": total, "footage_s": footage, "tail_hold_s": round(tail, 3), "shots": timeline,
                            "unused_clips": unused}


def rep_ticks(shots, timeline: list[dict], clips: dict[str, ClipInfo], start: float, end: float) -> list[float]:
    """Reel times at which a rep finishes, between start and end, from the clips' rep analysis."""
    out = []
    for sh, tl in zip(shots, timeline):
        if tl["end_s"] <= start or tl["start_s"] >= end:
            continue
        info = clips.get(sh.clip)
        for u in reps.in_range(info.reps if info else None, sh.in_s, sh.out_s):
            t = tl["start_s"] + (u - sh.in_s) / (sh.speed or 1.0)
            if start <= t <= end:
                out.append(round(t, 3))
    return sorted(out)


def _sync_counter(e, shots, timeline: list[dict], clips: dict[str, ClipInfo], footage: float) -> None:
    """A counter over exercise footage counts the real reps: one up each time a rep finishes.
    It runs on to the last rep of the shots it covers (within its maximum length)."""
    covered = [n for n, tl in enumerate(timeline) if tl["start_s"] < e.end_s and tl["end_s"] > e.start_s]
    if not covered:
        return
    last = covered[-1]
    while last + 1 < len(timeline):  # keep counting through the next shots that show reps too
        sh = shots[last + 1]
        info = clips.get(sh.clip)
        if not reps.in_range(info.reps if info else None, sh.in_s, sh.out_s):
            break
        last += 1
    span_end = min(timeline[last]["end_s"], footage, e.start_s + EFFECT_LIMITS["counter"][1])
    ticks = rep_ticks(shots, timeline, clips, e.start_s, span_end)
    if not ticks:
        return
    if ticks[-1] + 0.6 > e.end_s:
        e.end_s = round(min(span_end, ticks[-1] + 0.8), 3)
    ticks = [t for t in ticks if t < e.end_s - 0.1]
    first = e.numbers[0] if e.numbers else 0
    e.numbers = [first, first + len(ticks)]
    e.ticks_s = ticks


# graphic spots each caption position runs into (captions centre at 560 / 960 / 1150 px; see motion.ZONES)
CAPTION_CLASH = {"upper_third": {"top"}, "middle": {"middle", "bottom"}, "lower_middle": {"middle", "bottom"}}


def _clear_of_captions(e, captions, warnings: list[str]) -> None:
    """A graphic never sits on the captions shown at the same time: move it to a free spot, or, when
    it's on through captions everywhere (a counter running through a set), move those captions."""
    from app.services.motion import DEFAULT_POSITION

    during = [c for c in captions if c.start_s < e.end_s and e.start_s < c.end_s]
    busy = set().union(*(CAPTION_CLASH.get(c.position, {"middle", "bottom"}) for c in during))
    spot = e.position or DEFAULT_POSITION.get(e.type, "top")
    if spot not in busy:
        return
    name = e.type.replace("_", " ")
    free = next((p for p in ("top", "bottom", "middle") if p not in busy), None)
    if free:
        e.position = free
        warnings.append(f"Effect {name} at {e.start_s:.1f}s: moved to the {free} so it doesn't cover the captions")
        return
    to = "lower_middle" if spot == "top" else "upper_third"
    for c in during:
        if spot in CAPTION_CLASH.get(c.position, set()):
            c.position = to
            warnings.append(f"Caption {c.text!r}: moved to the {to.replace('_', ' ')}, clear of the {name}")


def _retime(plan: EditPlan, asked: list[tuple[float, float, float]], kept_idx: list[int], total: float) -> None:
    """Cuts moved (whole words, whole reps) or shots dropped: move every caption, effect, sound and
    card with the footage it was timed to, so a caption on a moment still lands on that moment."""
    now = {k: (s.in_s, s.out_s, s.speed) for k, s in zip(kept_idx, plan.shots)}
    if len(now) == len(asked) and all(abs(a - b) < 1e-3 for k, v in now.items() for a, b in zip(asked[k], v)):
        return
    old, t = [], 0.0
    for a_in, a_out, sp in asked:
        d = max(0.0, (a_out - a_in) / sp)
        old.append((t, t + d))
        t += d
    old_total = t
    new_start, t = {}, 0.0
    for k in kept_idx:
        new_start[k] = t
        i, o, sp = now[k]
        t += (o - i) / sp

    def move(x: float) -> float:
        if x >= old_total:
            return round(x - old_total + total, 3)
        for k, (a, b) in enumerate(old):
            if a <= x < b:
                if k not in now:  # dropped shot: to where the next kept one starts
                    later = [j for j in kept_idx if j > k]
                    return round(new_start[later[0]] if later else total, 3)
                a_in, _, sp = asked[k]
                i, o, nsp = now[k]
                clip_t = min(max(a_in + (x - a) * sp, i), o)
                return round(new_start[k] + (clip_t - i) / nsp, 3)
        return round(x, 3)

    for c in plan.captions:
        c.start_s, c.end_s = move(c.start_s), move(c.end_s)
    for e in plan.effects:
        e.start_s, e.end_s = move(e.start_s), move(e.end_s)
    for o in plan.overlays:
        o.start_s, o.end_s = move(o.start_s), move(o.end_s)
    for snd in plan.sounds:
        snd.at_s = move(snd.at_s)
