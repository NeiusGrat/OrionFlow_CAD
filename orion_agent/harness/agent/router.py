"""Pillar router.

Classifies each turn into query / modify / reconstruct / generate from the
message and the open model's tier. Deterministic and cheap (keyword + tier
heuristics) with an optional LLM tie-break; the build plan only requires a
working classifier, and a transparent one is easier to evaluate than a black box.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orion_agent.harness.agent.pillars import QUERY, MODIFY, RECONSTRUCT, GENERATE
from orion_agent.shared.contract import ModelTier

_MODIFY_VERBS = (
    "change", "increase", "decrease", "set ", "make ", "add ", "remove", "delete",
    "fillet", "chamfer", "resize", "scale", "move", "rotate", "thicken", "thin",
    "edit", "modify", "update", "replace", "extend", "shorten", "widen", "enlarge",
    "drill", "cut", "extrude", "pocket", "shell", "mirror", "pattern", "bolt circle",
)
_QUERY_CUES = (
    "how many", "how far", "what is", "what's", "which", "where", "measure",
    "distance", "volume", "dimension", "explain", "describe", "is the", "does the",
    "count", "list", "tell me", "show me", "?",
)
_RECONSTRUCT_CUES = (
    "drawing", "blueprint", "2d", "pdf", "scan", "reconstruct", "from this image",
    "legacy drawing", "technical drawing",
)
_GENERATE_CUES = (
    "create a new", "generate a", "make me a", "design a", "from scratch",
    "new model", "build a",
)


@dataclass
class RouteDecision:
    pillar: str
    confidence: float
    rationale: str


class PillarRouter:
    def route(
        self, message: str, tier: str = ModelTier.UNKNOWN, has_image: bool = False
    ) -> RouteDecision:
        text = message.lower().strip()

        # An attached 2D drawing is a strong reconstruct signal.
        if has_image or any(c in text for c in _RECONSTRUCT_CUES):
            return RouteDecision(RECONSTRUCT, 0.8, "drawing/2D reconstruction cue")

        if tier == ModelTier.EMPTY or any(c in text for c in _GENERATE_CUES):
            if any(c in text for c in _GENERATE_CUES) or tier == ModelTier.EMPTY:
                # Only generate when there is genuinely nothing to operate on or
                # the user explicitly asks for a brand-new model.
                if tier == ModelTier.EMPTY and not self._looks_like_query(text):
                    return RouteDecision(GENERATE, 0.7, "blank document + creation intent")
                if any(c in text for c in _GENERATE_CUES):
                    return RouteDecision(GENERATE, 0.7, "explicit 'new model' request")

        modify_hit = any(re.search(r"\b" + re.escape(v.strip()), text) for v in _MODIFY_VERBS)
        query_hit = self._looks_like_query(text)

        if modify_hit and not (query_hit and not self._imperative(text)):
            return RouteDecision(MODIFY, 0.75, "imperative edit verb present")
        if query_hit:
            return RouteDecision(QUERY, 0.8, "interrogative / measurement phrasing")

        # Default: read-only is the safe route (no mutation risk).
        return RouteDecision(QUERY, 0.4, "default safe route (read-only)")

    @staticmethod
    def _looks_like_query(text: str) -> bool:
        return any(c in text for c in _QUERY_CUES)

    @staticmethod
    def _imperative(text: str) -> bool:
        return any(text.startswith(v.strip()) for v in _MODIFY_VERBS)
