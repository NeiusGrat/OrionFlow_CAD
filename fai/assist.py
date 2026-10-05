"""The one place a frontier model plugs in — and what it is allowed to do.

The model *reads*; it never decides. On a sheet with no usable text layer
(scanned, or CAD text exported as outlines — 10 of 11 real NIST drawings) the
vision reader transcribes each callout and where it is. That text goes through
the same deterministic parsers as a text layer, tolerances still come from the
tables, CAD values from OpenCASCADE, and every status is arithmetic. Each
characteristic it produced is marked ``vision`` for the reviewer.

    ANTHROPIC_API_KEY           enables Claude (default model claude-opus-5-5)
    DRAWCHECK_VISION_MODEL      override, e.g. claude-sonnet-5-5 for cheaper iteration
    DRAWCHECK_CLAUDE_EFFORT     low | medium | high (default) | xhigh | max
    GEMINI_API_KEY              alternative provider, used only when DRAWCHECK_VISION_MODEL names a gemini model

With none set, sheets without text are reported as needing manual entry and
everything else still runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Assistant:
    model: str | None = None
    usage: Usage = field(default_factory=Usage)

    @property
    def configured(self) -> bool:
        return self.model is not None

    @property
    def name(self) -> str:
        return self.model or "none"

    def record(self, stats: dict) -> None:
        """Fold the vision reader's per-run totals into this run's usage."""
        if not stats:
            return
        self.model = stats.get("model") or self.model
        self.usage.calls += stats.get("pages", 0) - stats.get("cached_pages", 0)
        self.usage.input_tokens += stats.get("input_tokens", 0)
        self.usage.output_tokens += stats.get("output_tokens", 0)
        self.usage.cost_usd += stats.get("cost_usd", 0.0)


def from_env() -> Assistant:
    """Explicit only: a Claude key, or a model named in DRAWCHECK_VISION_MODEL.
    Never an implicit fallback to whichever other key happens to be in .env."""
    import os

    model = os.environ.get("DRAWCHECK_VISION_MODEL") or ("claude-opus-5-5" if os.environ.get("ANTHROPIC_API_KEY") else None)
    return Assistant(model)
