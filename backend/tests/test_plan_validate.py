import pytest

from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, PlanError, readable_s, validate

CLIPS = {
    "C1": ClipInfo("C1", 13.03),  # squats
    "C2": ClipInfo("C2", 11.52),  # selfie walk
    "C3": ClipInfo("C3", 5.18),   # low ground shot
    "C4": ClipInfo("C4", 2.31),   # sweaty selfie
}
STYLE = {"captions": {"max_words_on_screen": 7}, "look": {"accent_color": "#FF5A1F"}}


def shot(clip, a, b, speed=1.0, **kw):
    return {"clip": clip, "in_s": a, "out_s": b, "speed": speed, "zoom_from": 1.0, "zoom_to": 1.0,
            "focus_x": 0.5, "focus_y": 0.5, "keep_audio": False, "purpose": "", **kw}


def plan(shots, captions=(), overlays=()):
    return EditPlan.model_validate({
        "title": "Day 1", "summary": "", "shots": list(shots), "captions": list(captions),
        "overlays": list(overlays), "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0.5,
    })


def cap(text, a, b, highlight=None):
    return {"text": text, "start_s": a, "end_s": b, "position": "lower_middle", "highlight": highlight}


def test_day1_v3_plan_is_clean():
    """The timeline the user approved for Day 1 v3."""
    p = plan(
        [shot("C1", 0.5, 6.5), shot("C2", 3.8, 7.8), shot("C2", 10.0, 11.4), shot("C3", 0.3, 1.1),
         shot("C3", 1.1, 3.8, speed=0.9, zoom_from=1.7, zoom_to=1.8), shot("C4", 0, 2.3)],
        [cap("Day 1.", 0.3, 2.5), cap("First, a warm-up to open up my legs.", 2.7, 5.8),
         cap("Let's start.", 6.3, 9.8), {**cap("1.5 km done.", 12.3, 15.1, highlight="1.5 km"), "position": "upper_third"}],
        [{"type": "stats_card", "start_s": 17.5, "end_s": 23, "title": "DAY 1 · RUN",
          "items": [{"label": "Distance", "value": "2.06 km"}]}],
    )
    fixed, warnings, tl = validate(p, CLIPS, STYLE)
    assert warnings == [] and tl["unused_clips"] == []
    assert tl["footage_s"] == pytest.approx(17.5, abs=0.01)
    assert tl["shots"][4]["end_s"] - tl["shots"][4]["start_s"] == pytest.approx(3.0, abs=0.01)
    # the stats card runs after the footage -> last frame held for 5.5 s under it
    assert tl["tail_hold_s"] == pytest.approx(5.5, abs=0.01) and tl["total_s"] == pytest.approx(23.0, abs=0.01)
    assert fixed.overlays[0].end_s == pytest.approx(23.0, abs=0.01)


def test_out_of_range_shot_is_trimmed():
    fixed, warnings, _ = validate(plan([shot("C4", 0, 5.0)]), CLIPS)
    assert fixed.shots[0].out_s == 2.31 and any("trimmed" in w for w in warnings)


def test_unknown_clip_removed():
    fixed, warnings, _ = validate(plan([shot("C9", 0, 2), shot("C1", 0, 2)]), CLIPS)
    assert [s.clip for s in fixed.shots] == ["C1"] and any("unknown clip" in w for w in warnings)


def test_no_usable_shots():
    with pytest.raises(PlanError):
        validate(plan([shot("C9", 0, 2)]), CLIPS)


def test_overlapping_captions_moved_and_short_flagged():
    _, warnings, _ = validate(plan([shot("C1", 0, 10)], [cap("one two three", 0, 3), cap("Target: 2 km. Let's see.", 2.5, 3.9)]), CLIPS)
    assert any("overlapped" in w for w in warnings)
    assert any("needs" in w for w in warnings)


def test_only_one_highlight():
    fixed, warnings, _ = validate(
        plan([shot("C1", 0, 10)], [cap("1 km done.", 0, 2, "1 km"), cap("2 km done.", 3, 5, "2 km")]), CLIPS, STYLE
    )
    assert [c.highlight for c in fixed.captions] == ["1 km", None]


def test_speed_clamped():
    fixed, _, tl = validate(plan([shot("C1", 0, 4, speed=10)]), CLIPS)
    assert fixed.shots[0].speed == 2.0 and tl["total_s"] == 2.0


def test_readable():
    assert readable_s("Day 1.") == 1.1
    assert readable_s("Target: 2 km. Let's see.") == pytest.approx(2.0)


def test_tail_capped():
    p = plan([shot("C1", 0, 5)], overlays=[{"type": "stats_card", "start_s": 5, "end_s": 30, "title": "x", "items": []}])
    _, _, tl = validate(p, CLIPS)
    assert tl["tail_hold_s"] == 6.0 and tl["total_s"] == 11.0


def test_highlight_grows_to_number_with_unit():
    fixed, _, _ = validate(plan([shot("C1", 0, 10)], [cap("Target: 2 km. Let's see.", 0, 3, "2")]), CLIPS, STYLE)
    assert fixed.captions[0].highlight == "2 km"


def test_highlight_part_of_word_dropped():
    fixed, _, _ = validate(plan([shot("C1", 0, 10)], [cap("Let's start.", 0, 3, "tar")]), CLIPS, STYLE)
    assert fixed.captions[0].highlight is None


def test_caption_moved_below_stats_card_and_title_repeat_flagged():
    p = plan(
        [shot("C1", 0, 10)],
        [cap("Day 1.", 0.5, 1.9), {**cap("Day 1 ✓ Kal phir.", 7, 9.5), "position": "upper_third"}],
        [{"type": "title", "start_s": 0, "end_s": 1.8, "title": "DAY 1 · FIRST RUN", "items": []},
         {"type": "stats_card", "start_s": 6, "end_s": 10, "title": "DAY 1 · RUN", "items": []}],
    )
    fixed, warnings, _ = validate(p, CLIPS, STYLE)
    assert fixed.captions[1].position == "lower_middle"
    assert any("repeats caption" in w for w in warnings)


def test_caption_over_tight_shot_moves_up():
    p = plan([shot("C1", 0, 3), shot("C3", 0, 3, zoom_from=1.6, zoom_to=1.8)], [cap("Wide.", 0.5, 2.5), cap("1.5 km done.", 3.5, 5.5)])
    fixed, warnings, _ = validate(p, CLIPS, STYLE)
    assert [c.position for c in fixed.captions] == ["lower_middle", "upper_third"]


def test_unused_clips_reported():
    _, warnings, tl = validate(plan([shot("C1", 0, 3), shot("C3", 0, 2)]), CLIPS)
    assert tl["unused_clips"] == ["C2", "C4"]
    assert sum("isn't used" in w for w in warnings) == 2


# step 1 upgrades: cuts between words, effects -------------------------------------------


def test_cut_inside_a_word_moves_to_the_gap():
    words = [(0.5, 0.9), (1.0, 1.4), (2.0, 2.6)]  # "so" "today" ... "ran"
    clips = {"C1": ClipInfo("C1", 5.0, words)}
    p, warnings, _ = validate(plan([shot("C1", 1.2, 2.3, keep_audio=True)]), clips, None)
    assert (p.shots[0].in_s, p.shots[0].out_s) == (pytest.approx(0.94), pytest.approx(2.72))
    assert any("chop a word" in w for w in warnings)


def test_silent_shot_is_not_snapped_to_words():
    clips = {"C1": ClipInfo("C1", 5.0, [(1.0, 1.4)])}
    p, _, _ = validate(plan([shot("C1", 1.2, 3.0)]), clips, None)
    assert p.shots[0].in_s == 1.2


def fx_plan(effects):
    p = plan([shot("C1", 0, 6), shot("C2", 0, 6)])
    return EditPlan.model_validate({**p.model_dump(), "effects": effects})


def test_effects_are_cleaned_up():
    p, warnings, _ = validate(fx_plan([
        {"type": "punch_in", "start_s": 1.0, "end_s": 1.1, "text": "x", "look": "bw"},  # too short, stray fields
        {"type": "slow_push", "start_s": 1.2, "end_s": 4.0},  # starts inside the punch-in: removed
        {"type": "grade", "start_s": 5.0, "end_s": 9.0},  # no look -> moody
        {"type": "freeze_frame", "start_s": 6.0, "end_s": 9.5, "text": "  that's   me  "},  # 3 s max
        {"type": "flash", "start_s": 11.95, "end_s": 12.0},  # no room before the end
    ]), CLIPS, None)
    kinds = [(e.type, e.start_s, e.end_s) for e in p.effects]
    assert kinds == [("punch_in", 1.0, 1.4), ("grade", 5.0, 9.0), ("freeze_frame", 6.0, 9.0)]
    assert p.effects[0].text is None and p.effects[0].look is None
    assert p.effects[1].look == "moody"
    assert p.effects[2].text == "that's me"
    assert any("overlaps another zoom" in w for w in warnings)
    assert any("no room" in w for w in warnings)


def test_plans_saved_before_effects_still_load():
    old = plan([shot("C1", 0, 3)]).model_dump()
    old.pop("effects")
    assert EditPlan.model_validate(old).effects == []
