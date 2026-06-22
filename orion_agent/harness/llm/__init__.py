"""LLM client abstraction + concrete adapters.

One internal interface (chat + tool-calling + streaming + vision + a reasoning
channel). The model is a config value; the adapter boundary is where a future
self-hosted vLLM endpoint plugs in with no change to the agent loop.
"""

from orion_agent.harness.llm.base import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    ToolCallRequest,
)
from orion_agent.harness.llm.factory import get_llm_client

__all__ = [
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "ToolCallRequest",
    "get_llm_client",
]
