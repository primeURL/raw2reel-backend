"""Phase 4: the effects brain - reps counted from the footage, counters that tick on real reps,
graphics kept off the captions and the face, and every graphic heard."""
from pathlib import Path

import numpy as np
from PIL import Image

from app.services import motion as MO
from app.services import reps as R
from app.services import sfx as S
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, validate

SHOT = {"speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0, "focus_x": 0.5, "focus_y": 0.5, "keep_audio": False, "purpose": "",
        "transition_in": "cut", "clip": "C1", "in_s": 1.5, "out_s": 11.5}


def _plan(effects, captions=(), sounds=()) -> EditPlan:
    return EditPlan.model_validate({
        "title": "t", "summary": "", "shots": [SHOT], "captions": list(captions), "overlays": [], "effects": effects,
        "sound_effects": "subtle", "sounds": list(sounds), "music": {"enabled": False, "mood": "", "volume": "medium"},
        "end_fade_s": 0})


def test_reps_found_in_a_bobbing_body():
    t = np.arange(0, 12, 1 / R.FPS)
    rng = np.random.default_rng(1)
    curve = 0.5 + 0.06 * np.sin(2 * np.pi * (t - 0.5) / 2.0) + rng.normal(0, 0.004, len(t))  # a rep every 2 s
    curve[t > 11.2] = np.nan  # walks out of shot at the end: not a rep
    found = R.find_reps(curve)
    assert found and 5 <= found["count"] <= 6 and abs(found["period_s"] - 2.0) < 0.2
    assert all(u > d for d, u in zip(found["down_s"], found["up_s"]))


def test_no_reps_in_a_still_shot():
    rng = np.random.default_rng(2)
    assert R.find_reps(0.5 + rng.normal(0, 0.004, 120)) is None


def _workout_clip() -> ClipInfo:
    downs = [2.5, 4.5, 6.5, 8.5, 10.5, 12.5]
    return ClipInfo("C1", 14.0, [], {"count": 6, "down_s": downs, "up_s": [d + 1.0 for d in downs], "period_s": 2.0})


def test_counter_counts_the_real_reps():
    plan = _plan([{"type": "counter", "start_s": 0.2, "end_s": 2.0, "text": "PUSH-UPS", "numbers": [0, 50]}])
    out, _, _ = validate(plan, {"C1": _workout_clip()}, None)
    c = out.effects[0]
    # reps finish at 3.5, 5.5, 7.5, 9.5, 11.5 in the clip = 2 ... 10 on the reel (the shot starts at 1.5)
    assert c.ticks_s == [2.0, 4.0, 6.0, 8.0, 10.0]
    assert c.numbers == [0, 5] and c.end_s == 10.3  # the shot runs 0.3 s past the last rep, and the counter with it
    ticks = [s.at_s for s in out.sounds if s.sound == "tick"]
    assert ticks == c.ticks_s


def test_counter_without_reps_counts_on_its_own():
    plan = _plan([{"type": "counter", "start_s": 0.2, "end_s": 2.0, "numbers": [0, 50]}])
    out, _, _ = validate(plan, {"C1": ClipInfo("C1", 14.0)}, None)
    assert out.effects[0].ticks_s == [] and out.effects[0].numbers == [0, 50]


def test_graphic_moves_off_the_captions():
    cap = {"text": "hello there", "start_s": 0.5, "end_s": 3.0, "position": "upper_third", "highlight": None}
    plan = _plan([{"type": "notification", "start_s": 1.0, "end_s": 3.0, "text": "Mom", "items": ["Hi"]}], [cap])
    out, warnings, _ = validate(plan, {"C1": ClipInfo("C1", 14.0)}, None)
    assert out.effects[0].position == "bottom" and any("captions" in w for w in warnings)


def test_captions_make_room_for_a_long_graphic():
    caps = [{"text": "one", "start_s": 0.5, "end_s": 2.0, "position": "lower_middle", "highlight": None},
            {"text": "two", "start_s": 4.0, "end_s": 6.0, "position": "upper_third", "highlight": None}]
    plan = _plan([{"type": "counter", "start_s": 0.2, "end_s": 8.0, "numbers": [0, 9], "position": "middle"}], caps)
    out, _, _ = validate(plan, {"C1": ClipInfo("C1", 14.0)}, None)
    assert out.effects[0].position == "middle"  # nowhere free all along: it stays...
    assert [c.position for c in out.captions] == ["upper_third", "upper_third"]  # ...and the captions move up


class _Faces:
    found = 10

    def __init__(self, cy: float):
        self.cy = cy

    def boxes(self, a, b, step=0.2):
        return [(540.0, self.cy, 220.0)]


def test_graphic_moves_off_the_face():
    plan = _plan([{"type": "chat", "start_s": 1.0, "end_s": 3.0, "items": ["hi"], "position": "top"},
                  {"type": "price_tag", "start_s": 5.0, "end_s": 7.0, "numbers": [99], "position": "middle"}])
    notes: list[str] = []
    MO.keep_off_face(plan.effects, _Faces(500.0), 1920, notes)  # face high in the frame
    assert plan.effects[0].position == "bottom" and len(notes) == 1
    assert plan.effects[1].position == "middle"  # middle (from 650 px) is clear of a face at 370-630 px


def test_graphics_are_heard_with_the_ai_sound_design():
    plan = _plan([{"type": "notification", "start_s": 1.0, "end_s": 3.0, "text": "Mom", "items": ["Hi"]}],
                 sounds=[{"at_s": 5.0, "sound": "whoosh_fast", "level": "normal", "why": "cut"}])
    assert [(c.name, c.at_s) for c in S.cues(plan, 10)] == [("ding", 1.1), ("whoosh_fast", 5.0)]


def test_counter_template_ticks(tmp_path: Path):
    fx = {"title": "Reps", "items": [], "numbers": [0, 12], "unit": "", "position": "top", "accent": "#FF5A1F",
          "duration": 3.0, "ticks": [0.5, 1.0, 1.5, 2.0, 2.5]}
    fr = MO.render("counter", fx, 540, 960, 10, tmp_path / "c")
    orange = lambda p: int((lambda a: ((a[..., 0] > 200) & (a[..., 1] < 140) & (a[..., 3] > 200)).sum())(np.asarray(Image.open(p))))  # noqa: E731
    zero, five = orange(fr.at(0.4)), orange(fr.at(2.9))
    assert five != zero  # "0" before the first rep, "5" after five
    assert five < 1.5 * zero  # one digit: it shows the reps done, not the "12" it would ease up to


def test_ai_plan_schema_has_no_optional_fields():
    """The API refuses a strict schema with many optional fields ("compiled grammar is too large")."""
    from app.services.plan_schema import AIEditPlan

    s = AIEditPlan.model_json_schema()
    for name, d in {**s.get("$defs", {}), "AIEditPlan": s}.items():
        assert set(d.get("properties", {})) <= set(d.get("required", [])), name


def test_cuts_show_whole_reps():
    shot = {**SHOT, "in_s": 3.0, "out_s": 7.0}  # starts mid-rep (2.5 down, 3.5 up) and ends mid-rep (6.5 down)
    plan = _plan([])
    plan.shots[0].in_s, plan.shots[0].out_s = shot["in_s"], shot["out_s"]
    out, warnings, _ = validate(plan, {"C1": _workout_clip()}, None)
    assert (out.shots[0].in_s, out.shots[0].out_s) == (1.5, 7.8)  # from 1.5 (going down), to just after the rep ending 7.5
    assert any("whole" in w for w in warnings)


def test_counter_keeps_counting_into_the_next_rep_shot():
    second = {**SHOT, "in_s": 7.5, "out_s": 11.5}
    plan = _plan([{"type": "counter", "start_s": 0.2, "end_s": 2.0, "numbers": [0]}])
    plan.shots[0].out_s = 5.5
    plan.shots.append(plan.shots[0].model_copy(update={"in_s": second["in_s"], "out_s": second["out_s"]}))
    out, _, tl = validate(plan, {"C1": _workout_clip()}, None)
    c = out.effects[0]
    assert len(c.ticks_s) == 4 and c.numbers == [0, 4]  # 2 reps in each shot
    assert c.end_s > tl["shots"][1]["start_s"]


def test_ai_stats_card_becomes_an_overlay():
    from app.services import plan_ai
    from app.services.plan_schema import AIEditPlan

    base = _plan([]).model_dump()
    fx = {"start_s": 1.0, "end_s": 3.0, "look": None, "numbers": [], "unit": None, "position": None, "behind": False}
    base["shots"][0]["transition_in"] = "cut"
    ai = AIEditPlan.model_validate({**base, "story": [], "music": {"enabled": False, "mood": "", "volume": "medium"},
                                    "effects": [{**fx, "type": "stats_card", "text": "DAY 1", "items": ["Reps|10", "bad row"]},
                                                {**fx, "type": "flash", "text": None, "items": []}]})
    plan = plan_ai._as_plan(ai)
    assert [e.type for e in plan.effects] == ["flash"]
    assert plan.overlays[0].type == "stats_card" and plan.overlays[0].title == "DAY 1"
    assert [(i.label, i.value) for i in plan.overlays[0].items] == [("Reps", "10")]


def test_captions_move_with_the_footage_when_a_cut_moves():
    cap = {"text": "first rep", "start_s": 0.5, "end_s": 1.5, "position": "upper_third", "highlight": None}
    plan = _plan([], [cap])
    plan.shots[0].in_s = 3.0  # mid-rep: the cut moves back to 1.5, so the shot starts 1.5 s earlier
    out, _, _ = validate(plan, {"C1": _workout_clip()}, None)
    assert out.shots[0].in_s == 1.5
    assert (out.captions[0].start_s, out.captions[0].end_s) == (2.0, 3.0)  # still on clip 3.5-4.5
