"""The provider-agnostic LLM interface.

Every backend (k2v2 think today, a self-hosted vLLM endpoint later) implements
:class:`LLMClient`. The agent loop only ever sees this interface, so swapping
the model is a config change, never a code change.

Tool-calling is normalised here: a backend may support native OpenAI tool calls
or a prompt-based protocol; either way the loop receives
:class:`ToolCallRequest` objects.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]

    @staticmethod
    def new(name: str, arguments: dict) -> "ToolCallRequest":
        return ToolCallRequest(id=uuid.uuid4().hex[:12], name=name, arguments=arguments)


@dataclass
class LLMMessage:
    role: str                          # system | user | assistant | tool
    content: str = ""
    name: Optional[str] = None         # tool name for role == 'tool'
    tool_call_id: Optional[str] = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    images: list[str] = field(default_factory=list)   # file paths for vision

    @staticmethod
    def system(content: str) -> "LLMMessage":
        return LLMMessage("system", content)

    @staticmethod
    def user(content: str, images: Optional[list[str]] = None) -> "LLMMessage":
        return LLMMessage("user", content, images=images or [])

    @staticmethod
    def assistant(content: str, tool_calls=None) -> "LLMMessage":
        return LLMMessage("assistant", content, tool_calls=tool_calls or [])

    @staticmethod
    def tool(content: str, tool_call_id: str, name: str) -> "LLMMessage":
        return LLMMessage("tool", content, name=name, tool_call_id=tool_call_id)


@dataclass
class LLMResponse:
    content: str = ""
    thinking: str = ""                 # reasoning channel (k2v2 think)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"        # stop | tool_calls | length | error
    raw: Any = None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    """Abstract base. Concrete adapters implement :meth:`chat`."""

    supports_vision: bool = False
    supports_native_tools: bool = False

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        raise NotImplementedError

    # default: no streaming hook; adapters may override
    def chat_stream(self, messages, tools=None, on_token=None, **kw) -> LLMResponse:
        return self.chat(messages, tools=tools, **kw)
