"""Self-hosted vLLM adapter — the fine-tuned OrionFlow model.

Speaks the same OpenAI-compatible wire format as the k2think adapter, so the
agent loop is unchanged; only ``llm.provider`` moves. Two differences matter:

* **Streaming is real.** The fine-tuned model emits its derivation inside
  ``<think>`` before any geometry, and that reasoning is the thing an engineer
  wants to watch. :meth:`chat_stream` routes think-channel tokens and answer
  tokens to the callback separately so the panel can render them differently.
* **No auth theatre.** vLLM accepts any bearer token; there is no upstream
  rate-limit or 5xx storm to defend against, so the retry policy is thinner
  than k2think's.

Tool calls ride the same prompt-based protocol as every other backend.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from orion_agent.shared.config import get_config
from orion_agent.harness.llm.base import LLMClient, LLMMessage, LLMResponse
from orion_agent.harness.llm import tool_protocol

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"


class VLLMClient(LLMClient):
    supports_vision = False
    supports_native_tools = False      # prompt protocol, as with k2think

    def __init__(self, config=None):
        cfg = (config or get_config()).llm
        self.endpoint = self._normalise(cfg.base_url)
        self.api_key = cfg.api_key or "EMPTY"
        self.model = cfg.model
        self.default_temperature = cfg.temperature
        self.default_max_tokens = cfg.max_tokens
        self.timeout = cfg.request_timeout

    @staticmethod
    def _normalise(base_url: str) -> str:
        """Accept either a bare base ('http://h:8000/v1') or a full endpoint."""
        url = (base_url or "http://localhost:8000/v1").rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return url + "/chat/completions"

    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        payload = self._payload(messages, tools, temperature, max_tokens,
                                stream=False, model=model)
        try:
            body = self._post(payload)
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(content=f"[vllm transport error: {exc}]",
                               finish_reason="error")
        return self._parse(body)

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
        on_token: Optional[Callable[[str, str], None]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **_kw,
    ) -> LLMResponse:
        """Stream tokens, tagging each as ``"thinking"`` or ``"answer"``.

        ``on_token(channel, text)``. Falls back to a blocking call if the
        server or transport refuses to stream, so the caller never has to
        care which path it got.
        """
        payload = self._payload(messages, tools, temperature, max_tokens,
                                stream=True, model=model)
        pieces: list[str] = []
        in_think = False
        try:
            for delta in self._post_stream(payload):
                pieces.append(delta)
                if on_token is None:
                    continue
                # Track the think boundary across chunk splits by re-reading
                # the accumulated text; deltas can cut a tag in half.
                joined = "".join(pieces)
                now_in_think = (THINK_OPEN in joined
                                and THINK_CLOSE not in joined)
                if now_in_think != in_think:
                    in_think = now_in_think
                on_token("thinking" if in_think else "answer", delta)
        except Exception:  # noqa: BLE001 — streaming unsupported / dropped
            return self.chat(messages, tools=tools, temperature=temperature,
                             max_tokens=max_tokens)

        raw = "".join(pieces)
        thinking, answer = self._split_reasoning(raw)
        tool_calls = tool_protocol.parse_tool_calls(answer)
        return LLMResponse(
            content=tool_protocol.strip_tool_calls(answer),
            thinking=thinking,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            raw={"streamed": True},
        )

    # ------------------------------------------------------------------ #
    def _payload(self, messages, tools, temperature, max_tokens,
                 stream: bool, model: Optional[str] = None) -> dict:
        # A per-call override lets one endpoint serve both roles: the LoRA for
        # Blueprints, and the untouched base for conversation. The adapter is
        # trained to answer everything with a Blueprint, so asking it a
        # question returns JSON.
        return {
            "model": model or self.model,
            "messages": self._to_wire(messages, tools),
            "stream": stream,
            "temperature": (self.default_temperature if temperature is None
                            else temperature),
            "max_tokens": (self.default_max_tokens if max_tokens is None
                           else max_tokens),
        }

    def _to_wire(self, messages: list[LLMMessage],
                 tools: Optional[list[dict]]) -> list[dict]:
        wire: list[dict] = []
        rest = messages
        if tools:
            instr = tool_protocol.render_tool_instructions(tools)
            if messages and messages[0].role == "system":
                wire.append({"role": "system",
                             "content": messages[0].content + "\n\n" + instr})
                rest = messages[1:]
            else:
                wire.append({"role": "system", "content": instr})

        for m in rest:
            if m.role == "tool":
                wire.append({"role": "user",
                             "content": f"[tool:{m.name} result]\n{m.content}"})
            elif m.role == "assistant" and m.tool_calls:
                calls = "\n".join(
                    f'<tool_call>{{"name": "{tc.name}", "arguments": '
                    f"{json.dumps(tc.arguments)}}}</tool_call>"
                    for tc in m.tool_calls)
                wire.append({"role": "assistant",
                             "content": (m.content + "\n" + calls).strip()})
            else:
                content = m.content
                if m.role == "user" and m.images:
                    content += (
                        f"\n\n[Attachment note: {len(m.images)} image(s) were "
                        "attached, but this model cannot see images. Ask the "
                        "user for the dimensions or details you need instead "
                        "of guessing.]")
                wire.append({"role": m.role, "content": content})
        return wire

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def _post(self, payload: dict) -> dict:
        import urllib.request
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers=self._headers())
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _post_stream(self, payload: dict):
        """Yield content deltas from an SSE stream."""
        import urllib.request
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers={**self._headers(), "Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, ValueError, TypeError):
                    continue
                if delta:
                    yield delta

    # ------------------------------------------------------------------ #
    def _parse(self, body: dict) -> LLMResponse:
        try:
            choice = body["choices"][0]
            raw_content = choice["message"]["content"] or ""
            finish = choice.get("finish_reason", "stop")
        except (KeyError, IndexError, TypeError):
            return LLMResponse(content="[vllm: malformed response]",
                               finish_reason="error", raw=body)

        thinking, answer = self._split_reasoning(raw_content)
        tool_calls = tool_protocol.parse_tool_calls(answer)
        usage = body.get("usage", {}) or {}
        return LLMResponse(
            content=tool_protocol.strip_tool_calls(answer),
            thinking=thinking,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else finish,
            raw=body,
            usage={"prompt_tokens": usage.get("prompt_tokens", 0),
                   "completion_tokens": usage.get("completion_tokens", 0),
                   "total_tokens": usage.get("total_tokens", 0)},
        )

    @staticmethod
    def _split_reasoning(content: str) -> tuple[str, str]:
        """Split the trained ``<think>`` derivation from the Blueprint answer.

        The opening tag may be absent (some serving configs consume it), so the
        close tag is the authority — everything after the last one is answer.
        """
        if THINK_CLOSE not in content:
            return "", content.strip()
        head, _, tail = content.rpartition(THINK_CLOSE)
        return head.replace(THINK_OPEN, "").strip(), tail.strip()
