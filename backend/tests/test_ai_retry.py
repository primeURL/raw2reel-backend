"""AI calls ride out short network drops: slower extra attempts on connection errors only."""

import anthropic
import httpx
import pytest

from app.services import style_ai


class _Flaky:
    def __init__(self, fail_times: int):
        self.calls = 0
        self.fail_times = fail_times
        self.beta = self
        self.messages = self

    def parse(self, **_):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
        raise RuntimeError("reached the API")  # stands in for a real reply


def _run(monkeypatch, fail_times):
    fake = _Flaky(fail_times)
    sleeps = []
    monkeypatch.setattr(style_ai, "_client", lambda: fake)
    monkeypatch.setattr(style_ai.time, "sleep", sleeps.append)
    return fake, sleeps


def test_connection_drop_is_retried_after_a_wait(monkeypatch):
    fake, sleeps = _run(monkeypatch, fail_times=2)
    with pytest.raises(RuntimeError, match="reached the API"):
        style_ai._parse("sys", [{"type": "text", "text": "hi"}], None, "low")
    assert fake.calls == 3
    assert sleeps == list(style_ai.CONNECTION_WAITS_S)


def test_gives_up_with_a_clear_message(monkeypatch):
    fake, sleeps = _run(monkeypatch, fail_times=9)
    with pytest.raises(style_ai.StyleAIError, match="internet connection"):
        style_ai._parse("sys", [{"type": "text", "text": "hi"}], None, "low")
    assert fake.calls == len(style_ai.CONNECTION_WAITS_S) + 1
