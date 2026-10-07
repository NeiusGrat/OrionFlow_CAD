"""The one door to language models for OrionFlow Review.

Provider-agnostic (any OpenAI-compatible chat-completions endpoint, through
interface_check's client), strict JSON schemas, retries — and every call is
logged against its job: task, provider, model, tokens in/out, cost estimate,
latency, prompt version and a hash of the inputs, so an AI-derived value can be
traced and reproduced.

    REVIEW_AI                off | on (default on when a provider is configured)
    REVIEW_LLM_URL / _KEY / _MODEL      falls back to INTERFACE_CHECK_LLM_*
    REVIEW_LLM_PRICE_IN / _OUT          USD per million tokens (cost estimate; 0 = unknown)

With AI off, deterministic checks still run; AI-assisted steps report that
they did not run.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

PROMPT_VERSION = "2026-10-08"


def _env(name: str) -> str:
    return os.environ.get(f"REVIEW_{name}") or os.environ.get(f"INTERFACE_CHECK_{name}", "")


def provider():
    if os.environ.get("REVIEW_AI", "on").lower() == "off":
        return None
    url, key, model = _env("LLM_URL"), _env("LLM_KEY"), _env("LLM_MODEL")
    if not (url and key and model):
        return None
    from interface_check.llm import ChatCompletionsLLM
    return ChatCompletionsLLM(url, key, model, {}, timeout=float(_env("LLM_TIMEOUT") or 20), retries=int(_env("LLM_RETRIES") or 2))


class Gateway:
    """Looks like interface_check's LLM (``json``, ``available``), logs every call to ``rv_llm_calls``."""

    name = "review-gateway"

    def __init__(self, store=None, job_id: str | None = None, inner=None):
        self.store, self.job_id = store, job_id
        self.inner = inner if inner is not None else provider()
        self.price_in = float(os.environ.get("REVIEW_LLM_PRICE_IN", "0") or 0)
        self.price_out = float(os.environ.get("REVIEW_LLM_PRICE_OUT", "0") or 0)

    @property
    def available(self) -> bool:
        return self.inner is not None and getattr(self.inner, "available", True)

    def model_for(self, task: str) -> str:
        return self.inner.model_for(task) if self.inner else ""

    def json(self, task: str, prompt: str, schema: dict, images=()) -> dict:
        if not self.available:
            from interface_check.llm import LLMUnavailable
            raise LLMUnavailable("AI is not configured for this deployment")
        u = self.inner.usage
        before = (u.calls, u.cached, u.input_tokens, u.output_tokens)
        t0 = time.perf_counter()
        error = None
        try:
            return self.inner.json(task, prompt, schema, images)
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            tin, tout = u.input_tokens - before[2], u.output_tokens - before[3]
            cached = u.cached > before[1]
            if self.store is not None:
                self.store.log_llm_call(
                    job_id=self.job_id, task=task, provider=getattr(self.inner, "url", "") or self.inner.name,
                    model=self.model_for(task) or getattr(self.inner, "model", ""), tokens_in=tin, tokens_out=tout,
                    cost_usd=round(tin / 1e6 * self.price_in + tout / 1e6 * self.price_out, 6),
                    latency_ms=int((time.perf_counter() - t0) * 1000), cached=cached, prompt_version=PROMPT_VERSION,
                    inputs_hash=hashlib.sha256(json.dumps([prompt, schema], sort_keys=True).encode()).hexdigest()[:16],
                    error=error)
