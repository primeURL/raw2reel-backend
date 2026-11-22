from app.services.plan_ai import likely_retakes


def seg(text):
    return {"start": 0, "end": 1, "text": text}


def test_retakes_are_grouped():
    segs = [
        seg("So today I want to show you"),            # 0: false start
        seg("Okay again."),                            # 1
        seg("So today I want to show you my run."),    # 2: retake of 0
        seg("It was really hard but I did it."),       # 3
        seg("It was really hard, but I did it!"),      # 4: retake of 3
        seg("See you tomorrow."),                      # 5
    ]
    assert likely_retakes(segs) == [[0, 2], [3, 4]]


def test_different_lines_are_not_retakes():
    assert likely_retakes([seg("Day one of my run"), seg("Now the cool down"), seg("Done for today")]) == []
