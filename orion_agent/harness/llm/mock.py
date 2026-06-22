"""Deterministic mock LLM for offline tests and CI (no network).

Scriptable: queue a list of LLMResponse objects, or pass a callable that maps
the latest message list to a response. Lets the agent loop, pillars and eval
harness run with zero external calls.
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from orion_agent.harness.llm.base import LLMClient, LLMMessage, LLMResponse, ToolCallRequest


class MockClient(LLMClient):
    supports_vision = True
    supports_native_tools = False

    def __init__(self, config=None, script: Optional[list] = None,
                 responder: Optional[Callable] = None):
        self._script = list(script or [])
        self._responder = responder
        self.calls: list[list[LLMMessage]] = []

    def queue(self, *responses: Union[LLMResponse, str]) -> "MockClient":
        for r in responses:
            self._script.append(r if isinstance(r, LLMResponse) else LLMResponse(content=r))
        return self

    def tool(self, tool_name: str, arguments: Optional[dict] = None) -> "MockClient":
        self._script.append(
            LLMResponse(tool_calls=[ToolCallRequest.new(tool_name, arguments or {})],
                        finish_reason="tool_calls")
        )
        return self

    def chat(self, messages, tools=None, temperature=None, max_tokens=None) -> LLMResponse:
        self.calls.append(list(messages))
        if self._responder is not None:
            return self._responder(messages, tools)
        if self._script:
            return self._script.pop(0)
        return LLMResponse(content="(mock: no scripted response)")
