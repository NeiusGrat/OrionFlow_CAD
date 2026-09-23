"""api.ifm.ai 400s a multi-turn history whose assistant turns lack ``reasoning``.

Since 2026-09-23 the vendor answers "Add a supported thinking field to each
assistant message in the multi-turn conversation history" to any request with
a bare assistant message. The studio's second message onward, and the OFL
few-shot prompt, both carry one — so every such turn read as "no model is
reachable" while the endpoint was up. ``reasoning`` is the one field name both
Horizon and K2-Think-v2 accept; an empty string satisfies it.
"""

import io
import json
import urllib.error

from orion_agent.harness.llm import k2think
from orion_agent.harness.llm.base import LLMMessage, ToolCallRequest


def _client():
    return k2think.K2ThinkClient.__new__(k2think.K2ThinkClient)


def test_every_assistant_turn_carries_a_reasoning_field():
    wire = _client()._to_wire(
        [
            LLMMessage.system("sys"),
            LLMMessage.user("make a flange"),
            LLMMessage.assistant("done"),
            LLMMessage.assistant(
                "", tool_calls=[ToolCallRequest(id="1", name="t", arguments={})]
            ),
            LLMMessage.tool("result", "1", "t"),
            LLMMessage.user("thicker"),
        ],
        tools=None,
    )
    assistants = [m for m in wire if m["role"] == "assistant"]
    assert len(assistants) == 2
    assert all(m["reasoning"] == "" for m in assistants)
    assert all("reasoning" not in m for m in wire if m["role"] != "assistant")


def test_http_error_body_reaches_the_transport_error(monkeypatch):
    body = json.dumps({"detail": "Add a supported thinking field"}).encode()

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            "https://api.ifm.ai/v1/chat/completions", 400, "Bad Request",
            {}, io.BytesIO(body),
        )

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    c = _client()
    c.base_url, c.api_key, c.model = "https://api.ifm.ai/v1/chat/completions", "k", "m"
    c.default_temperature, c.default_max_tokens, c.timeout = 0.2, 100, 5
    resp = c.chat([LLMMessage.user("hi")])
    assert resp.finish_reason == "error"
    assert "400" in resp.content and "thinking field" in resp.content
