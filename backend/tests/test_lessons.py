"""Creator memory: lessons from change requests, fed to the AI and enforced in code. No network."""
from app.services import lessons as LS
from app.services import sfx as S
from app.services.plan_schema import EditPlan

SHOT = {"speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0, "focus_x": 0.5, "focus_y": 0.5, "keep_audio": False, "purpose": "",
        "transition_in": "whip", "clip": "C1", "in_s": 0, "out_s": 4}


def _plan(**kw) -> EditPlan:
    base = {"title": "t", "summary": "", "shots": [SHOT, SHOT], "overlays": [], "sound_effects": "punchy",
            "captions": [{"text": "hello", "start_s": 0.5, "end_s": 1.5, "position": "middle", "highlight": None}],
            "effects": [{"type": "flash", "start_s": 3.9, "end_s": 4.1}],
            "sounds": [{"at_s": 1.0, "sound": "pop", "level": "soft", "why": "x"},
                       {"at_s": 4.0, "sound": "whoosh_fast", "level": "normal", "why": "y"}],
            "music": {"enabled": True, "mood": "upbeat", "volume": "medium"}, "end_fade_s": 0}
    return EditPlan.model_validate({**base, **kw})


def test_known_lessons_are_not_learnt_twice():
    have = [{"text": "No pop sounds", "applies_to": "all", "rule": "no_sound:pop"}]
    assert LS.is_known("no pop sounds!", None, have)
    assert LS.is_known("Please skip those bubbly noises", "no_sound:pop", have)  # same switch
    assert not LS.is_known("Show every rep fully, down and up", "none", have)


def test_banned_sound_never_plays():
    plan = _plan()
    done = LS.enforce(plan, [{"text": "No pop sounds", "applies_to": "all", "rule": "no_sound:pop"}])
    assert [c.sound for c in plan.sounds] == ["whoosh_fast"] and done
    assert "pop" in plan.avoid_sounds
    plan.sounds = []  # with no sound design, punchy mode would pop on captions: still banned
    assert all(c.name != "pop" for c in S.cues(plan, 8))


def test_switch_lessons():
    plan = _plan()
    LS.enforce(plan, [{"text": "No fancy transitions", "applies_to": "all", "rule": "plain_cuts"},
                      {"text": "No flashes", "applies_to": "all", "rule": "no_effect:flash"},
                      {"text": "No music", "applies_to": "all", "rule": "no_music"}])
    assert {s.transition_in for s in plan.shots} == {"cut"} and plan.effects == [] and not plan.music.enabled


def test_kind_lessons_are_left_to_the_ai():
    plan = _plan()
    assert LS.enforce(plan, [{"text": "No pops in workouts", "applies_to": "workout", "rule": "no_sound:pop"}]) == []
    assert len(plan.sounds) == 2


def test_revision_returns_a_lesson_and_lessons_reach_the_ai(monkeypatch):
    from app.services import plan_ai

    seen = {}

    def fake_parse(system, content, fmt, effort):
        seen["system"], seen["text"] = system, " ".join(b.get("text", "") for b in content if b["type"] == "text")
        plan = _plan().model_dump()
        plan.update(story=[], music={"enabled": True, "mood": "upbeat", "volume": "medium"})
        plan["effects"] = [{**e, "text": None, "look": None, "items": [], "numbers": [], "unit": None, "position": None,
                            "behind": False} for e in plan["effects"]]
        return fmt.model_validate({"changes": ["Removed the pops"], "lesson": "No pop sounds", "lesson_applies_to": " All ",
                                   "lesson_rule": "no_sound:pop", "plan": plan}), {"model": "x"}

    monkeypatch.setattr(plan_ai, "_parse", fake_parse)
    clip = plan_ai.ClipInput("C1", 6.0, b"jpg", False, [], [], [])
    brief = LS.as_brief([type("L", (), {"text": "Show every rep fully", "applies_to": "workout"})()])
    _, changes, _, lesson = plan_ai.revise_plan([clip], None, "Food", None, "en", None, {"shots": []},
                                                "remove the pop sounds", None, brief)
    assert lesson == {"text": "No pop sounds", "applies_to": "all", "rule": "no_sound:pop"}
    assert "Show every rep fully" in seen["text"] and "creator_lessons" in seen["system"]


def test_revision_schema_fits_the_api():
    from app.services.plan_ai import AIRevision

    s = AIRevision.model_json_schema()
    for name, d in {**s.get("$defs", {}), "AIRevision": s}.items():
        assert set(d.get("properties", {})) <= set(d.get("required", [])), name


def test_a_sound_family_ban_covers_every_kind():
    plan = _plan(sounds=[{"at_s": 1.0, "sound": "whoosh_soft", "level": "soft", "why": "x"},
                         {"at_s": 4.0, "sound": "whoosh_fast", "level": "normal", "why": "y"},
                         {"at_s": 5.0, "sound": "slam", "level": "normal", "why": "z"}])
    LS.enforce(plan, [{"text": "No whoosh sounds", "applies_to": "all", "rule": "no_sound:whoosh"}])
    assert [c.sound for c in plan.sounds] == ["slam"]
    assert all(not c.name.startswith("whoosh") for c in S.cues(plan, 8))  # nor the automatic ones on the whips
