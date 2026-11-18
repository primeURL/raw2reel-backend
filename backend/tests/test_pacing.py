from app.tasks.analysis import pacing


def test_single_shot():
    p = pacing([], 10.0)
    assert p["shot_count"] == 1 and p["avg_shot_s"] == 10.0 and p["cuts_per_10s"] == 0


def test_cuts():
    # matches the "how to start running" reference: cuts at 4.67, 7.93, ...
    p = pacing([4.667, 7.933, 8.667, 10.333, 12.233, 19.033], 38.26)
    assert p["shot_count"] == 7
    assert p["shot_lengths"][0] == 4.67
    assert abs(sum(p["shot_lengths"]) - 38.26) < 0.05
    assert p["cuts_per_10s"] == round(10 * 6 / 38.26, 2)


def test_ignores_cuts_outside_video():
    assert pacing([-1, 0, 5, 12], 10)["shot_count"] == 2
