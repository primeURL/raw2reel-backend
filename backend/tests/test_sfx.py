from app.services import sfx as S
from app.services.plan_schema import EditPlan


def plan(mode, effects, captions=()):
    return EditPlan.model_validate({
        "title": "t", "summary": "", "shots": [], "overlays": [], "end_fade_s": 0,
        "music": {"enabled": False, "mood": "", "volume": "medium"},
        "captions": [{"text": "x", "start_s": a, "end_s": a + 1, "position": "middle", "highlight": None} for a in captions],
        "effects": effects, "sound_effects": mode,
    })


FX = [{"type": "punch_in", "start_s": 1.0, "end_s": 2.0}, {"type": "countdown", "start_s": 3.0, "end_s": 4.5},
      {"type": "grade", "start_s": 5.0, "end_s": 6.0, "look": "bw"}, {"type": "backdrop_word", "start_s": 7.0, "end_s": 9.0, "text": "GO"}]


def test_each_effect_gets_its_sound():
    cues = S.cues(plan("subtle", FX, captions=[0.5, 1.0]), 20)
    assert [(c.name, round(c.at_s, 2)) for c in cues] == [
        ("whoosh_fast", 1.06), ("tick", 3.0), ("tick", 3.5), ("tick", 4.0), ("slam", 7.25)]  # grade is silent


def test_off_is_silent_and_punchy_pops_captions_not_too_often():
    assert S.cues(plan("off", FX), 20) == []
    pops = [c.at_s for c in S.cues(plan("punchy", [], captions=[0.5, 1.0, 2.2, 2.5]), 20) if c.name == "pop"]
    assert pops == [0.5, 2.2]


def test_old_plans_get_subtle_sounds():
    p = plan("subtle", []).model_dump()
    p.pop("sound_effects")
    assert EditPlan.model_validate(p).sound_effects == "subtle"


def test_every_pack_sound_exists_in_three_takes():
    names = {"whoosh_fast", "whoosh_soft", "boom", "slam", "shutter", "tick", "pop"}
    for n in names:
        for k in range(1, S.TAKES + 1):
            path = S.SFX_DIR / f"{n}_{k}.ogg"
            assert path.exists() and 0 <= S.hit_offset(path) < 0.6, path


def test_mix_graph_rotates_takes_and_numbers_inputs():
    cues = [S.Cue("tick", 1.0), S.Cue("tick", 2.0), S.Cue("tick", 3.0), S.Cue("tick", 4.0)]
    inputs, chains, labels = S.mix_graph(cues, "subtle", first_input=5)
    files = [x.rsplit("/", 1)[-1] for x in inputs[1::2]]
    assert files == ["tick_1.ogg", "tick_2.ogg", "tick_3.ogg", "tick_1.ogg"]
    assert chains[0].startswith("[5:a]") and chains[3].startswith("[8:a]") and len(labels) == 4
