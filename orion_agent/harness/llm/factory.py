"""LLM client factory — provider is a config value."""

from __future__ import annotations

from typing import Optional

from orion_agent.shared.config import get_config
from orion_agent.harness.llm.base import LLMClient


def get_llm_client(provider: Optional[str] = None, config=None) -> LLMClient:
    cfg = config or get_config()
    provider = provider or cfg.llm.provider

    if provider == "k2think":
        from orion_agent.harness.llm.k2think import K2ThinkClient
        return K2ThinkClient(cfg)
    if provider == "mock":
        from orion_agent.harness.llm.mock import MockClient
        return MockClient(cfg)
    if provider in ("openai", "vllm"):
        # Self-hosted fine-tuned OrionFlow model behind an OpenAI-compatible
        # server. Same interface, so the agent loop is untouched.
        from orion_agent.harness.llm.vllm_client import VLLMClient
        return VLLMClient(cfg)
    raise ValueError(f"unknown LLM provider: {provider}")
