"""The 429 backoff, which used to cost more than the model did.

The gateway in front of K2-Think sends a blanket ``Retry-After: 60`` on every
429 regardless of state, and the limiter actually refills in under half a
second (measured 2026-09-02: a request 0.5s after a 429 returns 200, as do 1s,
2s and 3s). One studio turn makes two calls back to back, so the second
reliably tripped the limiter — and the old code then slept its 30s cap.

A verified flange took 37.8s, of which 30.0s was that sleep and 3.5s was the
model. The system looked like it was waiting on a slow reasoning model. It was
waiting on itself. After the fix the same prompt takes 16.0s, 1.0s of it asleep.
"""

import time
import urllib.error
import urllib.request

import pytest

from orion_agent.harness.llm import k2think


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def _client():
    return k2think.K2ThinkClient.__new__(k2think.K2ThinkClient)


def _too_many(retry_after="60"):
    return urllib.error.HTTPError(
        "https://api.k2think.ai/v1/chat/completions", 429, "Too Many Requests",
        {"Retry-After": retry_after}, None,
    )


@pytest.fixture
def limiter(monkeypatch):
    """One 429 then success, recording every sleep the client takes."""
    slept: list[float] = []
    calls = {"n": 0}

    def urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _too_many()
        return _Resp(b'{"choices":[{"message":{"content":"ok"},'
                     b'"finish_reason":"stop"}],"usage":{}}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept, calls


def test_a_blanket_retry_after_does_not_become_a_thirty_second_stall(limiter):
    slept, calls = limiter
    c = _client()
    c.base_url, c.api_key, c.timeout = k2think.K2ThinkClient._ENDPOINT, "k", 30.0

    body = c._post({"model": "m", "messages": []})

    assert body["choices"][0]["message"]["content"] == "ok"
    assert calls["n"] == 2, "the 429 must be retried, not raised"
    # The server said 60. We wait 1, because 60 is not true.
    assert slept == [1.0], slept


def test_a_server_asking_for_less_is_still_obeyed(monkeypatch):
    """Retry-After is a ceiling, not something to ignore. A gateway that ever
    sends a plausible value must not be overridden upward by our own floor."""
    slept: list[float] = []
    calls = {"n": 0}

    def urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _too_many(retry_after="0.25")
        return _Resp(b'{"choices":[{"message":{"content":"ok"},'
                     b'"finish_reason":"stop"}],"usage":{}}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(time, "sleep", slept.append)
    c = _client()
    c.base_url, c.api_key, c.timeout = k2think.K2ThinkClient._ENDPOINT, "k", 30.0

    c._post({"model": "m", "messages": []})

    assert slept == [0.25], slept


def test_a_sustained_limit_backs_off_geometrically_then_gives_up(monkeypatch):
    """Retrying forever is its own outage. Five attempts, ~15s worst case —
    against 30s for the single retry the old code allowed."""
    slept: list[float] = []
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(_too_many()),
    )
    monkeypatch.setattr(time, "sleep", slept.append)
    c = _client()
    c.base_url, c.api_key, c.timeout = k2think.K2ThinkClient._ENDPOINT, "k", 30.0

    with pytest.raises(urllib.error.HTTPError):
        c._post({"model": "m", "messages": []})

    assert slept == [1.0, 2.0, 4.0, 8.0], slept
    assert sum(slept) < 30.0, "worst case must beat the old single 30s sleep"


def test_a_permanent_4xx_is_still_permanent(monkeypatch):
    """Only 429 and 5xx are transient. Retrying a 401 just delays the truth."""
    slept: list[float] = []

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(time, "sleep", slept.append)
    c = _client()
    c.base_url, c.api_key, c.timeout = k2think.K2ThinkClient._ENDPOINT, "k", 30.0

    with pytest.raises(urllib.error.HTTPError):
        c._post({"model": "m", "messages": []})
    assert slept == []
