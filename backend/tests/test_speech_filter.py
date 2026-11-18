from types import SimpleNamespace

from app.services.analysis import Word, _is_real_speech


def seg(text, no_speech=0.05, logprob=-0.2):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


def words(*probs):
    return [Word(f"w{i}", i * 0.3, i * 0.3 + 0.25, p) for i, p in enumerate(probs)]


def test_keeps_clear_speech():
    assert _is_real_speech(seg("Sabse pehle body ko running ke liye prepare karna hai"), words(0.9, 0.8, 0.95, 0.85))


def test_drops_wind_hallucination():
    # what Whisper produced on the windy selfie-walk clip
    assert not _is_real_speech(seg(" You", no_speech=0.5, logprob=-0.9), words(0.4))


def test_drops_low_confidence():
    assert not _is_real_speech(seg("some mumbled thing"), words(0.2, 0.3, 0.4))


def test_drops_no_speech_segment():
    assert not _is_real_speech(seg("Thanks for watching!", no_speech=0.9, logprob=-1.2), words(0.6, 0.6, 0.6))


def test_keeps_confident_short_reply():
    assert _is_real_speech(seg("Okay.", no_speech=0.05), words(0.95))


def test_empty():
    assert not _is_real_speech(seg(""), [])
