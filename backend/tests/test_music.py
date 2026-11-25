"""Phase 1 sound library: beat finding, track choice, music in the mix (dipped under speech),
library sounds in the plan. No network: the library is set in memory. ~20 s."""
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.services import analysis as A
from app.services import beats as B
from app.services import library as L
from app.services import music as M
from app.services import render as R
from app.services.plan_schema import EditPlan
from app.services.plan_validate import ClipInfo, validate

SHOT = {"speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0, "focus_x": 0.5, "focus_y": 0.5, "keep_audio": True, "purpose": "",
        "transition_in": "cut"}


def _track(tid, moods, energy="medium", dur=60.0, **kw):
    return {"id": tid, "title": tid, "moods": moods, "energy": energy, "duration_s": dur, "bpm": 120,
            "beats": [round(0.5 * k, 3) for k in range(int(dur * 2))], "key": f"library/music/{tid}.m4a", **kw}


@pytest.fixture(autouse=True)
def empty_library():
    L.set_manifest({"version": 1, "music": [], "sfx": []})
    yield
    L.set_manifest({"version": 1, "music": [], "sfx": []})


def _plan(**over) -> EditPlan:
    base = {"title": "t", "summary": "", "shots": [{"clip": "C1", "in_s": 0, "out_s": 6, **SHOT}], "captions": [],
            "overlays": [], "effects": [], "sound_effects": "subtle", "sounds": [],
            "music": {"enabled": True, "mood": "upbeat", "volume": "low_under_voice"}, "end_fade_s": 0}
    base.update(over)
    return EditPlan.model_validate(base)


def test_finds_tempo_and_beats(tmp_path: Path):
    wav = tmp_path / "click.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.8*sin(2*PI*60*t)*exp(-30*mod(t-0.25,0.5))*lt(mod(t-0.25,0.5),0.15)*gte(t,0.25)':s=44100:d=16",
                    str(wav)], check=True)
    a = B.analyse(wav)
    assert abs(a.bpm - 120) < 2
    expected = np.arange(0.25, 15.5, 0.5)
    hits = [b for b in a.beats if np.min(np.abs(expected - b)) < 0.04]
    assert len(hits) >= 0.9 * len(a.beats) and len(a.beats) >= 28


def test_music_starts_where_cuts_hit_beats():
    beats = [0, 1, 2, 3, 3.5, 4, 5, 6, 7, 8]
    assert B.best_offset(beats, [0.5], 9, 3) == 3.0  # only from 3 s does the cut land on a beat (3.5)
    assert B.best_offset(beats, [], 9, 3) == 0.0


def test_track_choice_follows_mood_energy_and_seed():
    L.set_manifest({"version": 1, "sfx": [], "music": [
        _track("calm-a", ["chill"], "calm"), _track("up-a", ["upbeat"], "medium"), _track("up-b", ["upbeat", "desi"], "high"),
        _track("up-short", ["upbeat"], "medium", dur=10), _track("gone", ["upbeat"], blocked=True)]})
    assert L.choose_music("warm upbeat acoustic", "high", "p1")["id"] == "up-b"
    assert L.choose_music("upbeat", "medium", "p1", reel_s=30)["id"] == "up-a"  # long enough not to loop
    assert L.choose_music("chill", None, "p1")["id"] == "calm-a"
    assert L.choose_music("upbeat", "medium", "p9")["id"] == L.choose_music("upbeat", "medium", "p9")["id"]
    assert "gone" not in {t["id"] for t in L.music_tracks()}
    assert L.moods_available() == ["upbeat", "chill", "desi"]
    plan = _plan()
    assert M.assign(plan, "p1")["id"] == "up-a" and plan.music.track == "up-a"
    plan.music.track = "calm-a"  # the creator's pick stays
    assert M.assign(plan, "p1")["id"] == "calm-a"


def test_library_sounds_only_when_we_have_them():
    snd = {"at_s": 2.0, "sound": "riser", "level": "normal", "why": "reveal"}
    plan, warnings, _ = validate(_plan(sounds=[snd]), {"C1": ClipInfo("C1", 6.0)}, None)
    assert plan.sounds == [] and any("riser" in w for w in warnings)
    L.set_manifest({"version": 1, "music": [], "sfx": [{"id": "r1", "category": "riser", "key": "library/sfx/riser/r1.m4a"}]})
    plan, _, _ = validate(_plan(sounds=[snd]), {"C1": ClipInfo("C1", 6.0)}, None)
    assert [s.sound for s in plan.sounds] == ["riser"]


def test_creator_music_choice_wins():
    from app.services import prefs as P

    plan = _plan()
    P.enforce(plan, {"music": {"track": "up-b", "volume": "music_led"}})
    assert plan.music.enabled and plan.music.track == "up-b" and plan.music.volume == "music_led"
    P.enforce(plan, {"music": {"enabled": False}})
    assert not plan.music.enabled
    assert "No background music" in P.ai_note({"music": {"enabled": False}})


def test_old_plans_load_without_a_track():
    p = EditPlan.model_validate({**_plan().model_dump(), "music": {"enabled": True, "mood": "chill", "volume": "medium"}})
    assert p.music.track is None


def _band_db(path: Path, t0: float, t1: float, freq: int) -> float:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t0), "-t", str(t1 - t0), "-i", str(path), "-af",
                          ",".join([f"bandpass=f={freq}:width_type=q:w=8"] * 3), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    return 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9)


def test_music_is_mixed_in_and_dips_under_speech(tmp_path: Path, monkeypatch):
    # the clip: someone "talking" (a 220 Hz tone) for 3 s, then quiet
    raw = tmp_path / "C1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:size=1080x1920:rate=30",
                    "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*220*t)*lt(t,3)':s=48000", "-t", "6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(raw)], check=True)
    src = {"C1": (A.make_proxy(raw, tmp_path / "C1_p.mp4"), True)}
    song = tmp_path / "song.m4a"  # the music: a steady 880 Hz tone, levelled like the library's
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100", "-t", "20",
                    "-af", "volume=-12dB", "-c:a", "aac", str(song)], check=True)
    L.set_manifest({"version": 1, "sfx": [], "music": [_track("song", ["upbeat"], dur=20)]})
    monkeypatch.setattr(L, "fetch", lambda key: song)

    plan, _, tl = validate(_plan(), {"C1": ClipInfo("C1", 6.0)}, None)
    M.assign(plan, "p")
    res = R.render(plan, tl, src, None, tmp_path / "out", quality="preview")
    under_voice, alone = _band_db(res.path, 1.0, 2.5, 880), _band_db(res.path, 4.2, 5.6, 880)
    assert alone > -60, alone  # the music plays (this band filter reads a full-scale tone at about -20)
    assert alone - under_voice > 4, (under_voice, alone)  # and dips while the voice talks
    assert _band_db(res.path, 1.0, 2.5, 220) > under_voice  # the voice stays on top

    plan.music.enabled = False
    quiet = R.render(plan, tl, src, None, tmp_path / "out2", quality="preview")
    assert _band_db(quiet.path, 4.2, 5.6, 880) < alone - 20  # no music when it's off


def test_older_free_text_moods_still_match():
    L.set_manifest({"version": 1, "sfx": [], "music": [_track("c", ["chill"]), _track("i", ["inspiring"]), _track("u", ["upbeat"])]})
    assert L.choose_music("calm, light, warm, gentle feel-good kitchen groove", None, "p")["id"] in {"c", "u"}
    assert L.choose_music("calm, steady, quietly motivating", "medium", "p")["id"] in {"c", "i"}
