"""k2v2 think adapter — MBZUAI-IFM K2-Think-v2.

Targets the official developer API at ``api.k2think.ai/v1/chat/completions``,
which is OpenAI-compatible (standard ``choices[0].message.content``). The model
emits its chain-of-thought inline, terminated by a ``</think>`` marker; this
adapter splits that reasoning out of the final answer.

Tool calls are carried by the prompt-based protocol
(:mod:`orion_agent.harness.llm.tool_protocol`) so the agent loop always receives
structured tool-call requests. A future self-hosted vLLM endpoint can replace
this adapter without touching the loop.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from orion_agent.shared.config import get_config
from orion_agent.harness.llm.base import LLMClient, LLMMessage, LLMResponse
from orion_agent.harness.llm import tool_protocol

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
)


def _usage_of(body: dict) -> dict:
    usage = body.get("usage", {}) or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


class K2ThinkClient(LLMClient):
    supports_vision = False            # text-only reasoning model
    supports_native_tools = False      # tool calls via prompt protocol

    #: This vendor's own settings, used when it is not the configured provider.
    #:
    #: Reading ``cfg.llm.*`` unconditionally is what broke the fallback. Those
    #: fields describe *the configured provider* — with vLLM primary they hold
    #: the self-hosted endpoint and the model name ``orionflow``. So the
    #: fallback posted a request for our fine-tune to the very GPU whose being
    #: unreachable is the only reason a fallback runs at all, and the studio had
    #: no working model the moment that box went down.
    #:
    #: When k2think *is* the configured provider the generic names still win, so
    #: an existing deployment that points ORION_LLM_BASE_URL at k2think is
    #: unaffected.
    _ENDPOINT = "https://api.k2think.ai/v1/chat/completions"
    _MODEL = "MBZUAI-IFM/K2-Think-v2"

    def __init__(self, config=None):
        cfg = (config or get_config()).llm
        own = cfg.provider == "k2think"

        def _own(name: str, default: str) -> str:
            return os.environ.get(name) or default

        self.base_url = (
            cfg.base_url if own and cfg.base_url
            else _own("K2THINK_BASE_URL", self._ENDPOINT)
        )
        self.api_key = (
            cfg.api_key if own and cfg.api_key
            else _own("K2THINK_API_KEY", cfg.api_key)
        )
        self.model = (
            cfg.model if own and cfg.model
            else _own("K2THINK_MODEL", self._MODEL)
        )
        self.default_temperature = cfg.temperature
        self.default_max_tokens = cfg.max_tokens
        self.timeout = cfg.request_timeout

    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        wire = self._to_wire(messages, tools)
        budget = self.default_max_tokens if max_tokens is None else max_tokens
        payload = {
            "model": self.model,
            "messages": wire,
            "stream": False,
            "temperature": self.default_temperature if temperature is None else temperature,
            "max_tokens": budget,
        }
        try:
            body = self._post(payload)
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(content=f"[k2think transport error: {exc}]", finish_reason="error")
        resp = self._parse(body)

        # K2-Think's long inline reasoning can push the actual tool call past the
        # token budget, truncating it so it cannot be parsed. Detect that and
        # retry once with a bigger budget rather than leaking a half-emitted call.
        cap = 16384
        if self._is_truncated(resp, body) and budget < cap:
            payload["max_tokens"] = min(cap, budget * 2)
            try:
                body = self._post(payload)
                resp = self._parse(body)
            except Exception:  # noqa: BLE001
                pass
        return resp

    @staticmethod
    def _is_truncated(resp: LLMResponse, body: dict) -> bool:
        try:
            choice = body["choices"][0]
            finish = choice.get("finish_reason", "")
            # ``.get``, not ``[...]``: K2-Think omits ``content`` entirely when
            # the budget dies mid-thought — see ``_parse``. Subscripting raised
            # KeyError, which was caught below as "not truncated", so the retry
            # never fired in the one case it exists for. The caller then saw an
            # empty reply and read it as a model with nothing to say.
            raw = (choice.get("message") or {}).get("content") or ""
        except (KeyError, IndexError, TypeError):
            return False
        if finish == "length":
            return True
        # An opened <tool_call> tag in the raw output but nothing parsed back out
        # => the call was cut off mid-emission.
        return not resp.tool_calls and "<tool_call>" in raw

    # ------------------------------------------------------------------ #
    def _to_wire(self, messages: list[LLMMessage], tools: Optional[list[dict]]) -> list[dict]:
        wire: list[dict] = []
        if tools:
            instr = tool_protocol.render_tool_instructions(tools)
            if messages and messages[0].role == "system":
                wire.append({"role": "system", "content": messages[0].content + "\n\n" + instr})
                rest = messages[1:]
            else:
                wire.append({"role": "system", "content": instr})
                rest = messages
        else:
            rest = messages

        for m in rest:
            if m.role == "tool":
                wire.append({"role": "user", "content": f"[tool:{m.name} result]\n{m.content}"})
            elif m.role == "assistant" and m.tool_calls:
                calls = "\n".join(
                    f'<tool_call>{{"name": "{tc.name}", "arguments": '
                    f"{json.dumps(tc.arguments)}}}</tool_call>"
                    for tc in m.tool_calls
                )
                wire.append({"role": "assistant", "content": (m.content + "\n" + calls).strip()})
            else:
                content = m.content
                if m.role == "user" and m.images:
                    # Never drop attachments silently: the model must know it
                    # cannot see them, or it will hallucinate their contents.
                    content += (
                        f"\n\n[Attachment note: {len(m.images)} image(s) were "
                        "attached, but this model cannot see images. Ask the "
                        "user for the dimensions or details you need instead "
                        "of guessing.]"
                    )
                wire.append({"role": m.role, "content": content})
        return wire

    def _post(self, payload: dict) -> dict:
        import time
        import urllib.error
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )
        # Transient network failures (DNS getaddrinfo blips, dropped sockets,
        # read timeouts, 5xx) shouldn't kill the whole agent turn — retry a few
        # times with backoff. Auth/4xx errors are permanent, so don't retry them
        # — with one exception.
        #
        # 429 is the one 4xx that is explicitly transient: it means "you asked
        # too fast", and HTTP defines ``Retry-After`` for exactly this. Lumping
        # it in with 401/404 made a rate limit look like a dead endpoint, and
        # the caller then put the provider on a 120 s cooldown — so a burst of
        # requests (a benchmark run, or any busy minute) knocked the only
        # provider out and every prompt behind it reported that no model was
        # reachable. Retrying here costs one sleep; not retrying cost the run.
        attempts = 3
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                retryable = exc.code >= 500 or exc.code == 429
                if not retryable or i == attempts - 1:
                    raise
                last_exc = exc
                if exc.code == 429:
                    # Honour the server's own pacing when it gives one. Capped:
                    # a hostile or absent value must not stall the turn.
                    try:
                        wait = float(exc.headers.get("Retry-After") or 0)
                    except (TypeError, ValueError):
                        wait = 0.0
                    time.sleep(min(max(wait, 2.0 * (i + 1)), 30.0))
                    continue
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if i == attempts - 1:
                    raise
                last_exc = exc
            time.sleep(1.5 * (i + 1))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("k2think: no response")

    # ------------------------------------------------------------------ #
    def _parse(self, body: dict) -> LLMResponse:
        try:
            choice = body["choices"][0]
            message = choice["message"]
            finish = choice.get("finish_reason", "stop")
        except (KeyError, IndexError, TypeError):
            return LLMResponse(
                content="[k2think: malformed response]", finish_reason="error", raw=body
            )

        # K2-Think v2 returns the derivation in its own ``reasoning`` field and
        # omits ``content`` entirely when the token budget ran out mid-thought.
        # Requiring ``content`` therefore reported a working endpoint as
        # malformed, which reads as "the vendor is broken" rather than "ask for
        # more tokens". v1 inlined the reasoning in ``content``, so both shapes
        # are accepted: an explicit field wins, otherwise fall back to splitting.
        raw_content = message.get("content") or ""
        field_reasoning = (message.get("reasoning") or "").strip()
        if field_reasoning:
            thinking, answer = field_reasoning, raw_content.strip()
        else:
            thinking, answer = self._split_reasoning(raw_content)

        if not answer and thinking and finish == "length":
            # All budget went to the derivation. Say so — an empty string here
            # is indistinguishable from a model that had nothing to add.
            return LLMResponse(
                content="",
                thinking=thinking,
                finish_reason="length",
                raw=body,
                usage=_usage_of(body),
            )
        tool_calls = tool_protocol.parse_tool_calls(answer)
        clean = tool_protocol.strip_tool_calls(answer)
        return LLMResponse(
            content=clean,
            thinking=thinking,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else finish,
            raw=body,
            usage=_usage_of(body),
        )

    @staticmethod
    def _split_reasoning(content: str) -> tuple[str, str]:
        """Separate K2-Think's inline chain-of-thought from the final answer.

        The model terminates reasoning with ``</think>`` (the opening tag may be
        absent). Everything after the last ``</think>`` is the answer; an
        explicit ``<answer>...</answer>`` block, if present, wins.
        """
        ans_i = content.find("<answer>")
        ans_j = content.rfind("</answer>")
        if ans_i != -1 and ans_j != -1 and ans_j > ans_i:
            answer = content[ans_i + len("<answer>"):ans_j].strip()
            thinking = content[:ans_i].replace("<think>", "").replace("</think>", "").strip()
            return thinking, answer

        end = content.rfind("</think>")
        if end != -1:
            thinking = content[:end].replace("<think>", "").strip()
            answer = content[end + len("</think>"):].strip()
            return thinking, answer
        return "", content.strip()
