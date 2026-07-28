"""The studio's agent: our own model, from prompt to a part that proved itself.

Two roles, deliberately not blended.

**Design** frames the request exactly as the fine-tuned model was trained and
evaluated — ``orion.pack_sft.SYSTEM_PROMPT``, one user turn, nothing else. It
is tempting to enrich that turn with knowledge-base facts, and it would be a
mistake: 94% VERIFIED was measured on this distribution, and every token added
to the prompt moves the model off it. Grounding therefore travels *beside* the
design call (shown to the user, available to the conversation role), never
inside it.

**Conversation** is the opposite case. Explaining a choice, quoting a standard,
or arguing about wall thickness is ordinary instruction-following over the
harness knowledge tools, and it runs with the part and its verification report
in context so the assistant is talking about *this* part.

Both roles resolve their backend through ``orion_agent.harness.llm``, so which
model answers is a config value. When the fine-tuned endpoint is unreachable
the fallback is used and **labelled as such** in the stream — a demo that
quietly degrades to a general model is worse than one that stops, because
nobody can tell which system produced the result.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

EventSink = Optional[Callable[[str, dict], None]]

#: Providers that serve OUR fine-tuned weights. Anything else is somebody
#: else's model and must be labelled as a fallback, however well it answers.
OURS = ("vllm", "openai")


def _providers() -> tuple[str, str]:
    """(primary, fallback), resolved at call time.

    Deliberately not module-level constants: ``.env`` is loaded lazily by
    ``orion_agent.shared.config``, so reading the environment at import time
    can miss it entirely and silently pick a different model than configured.
    """
    from orion_agent.shared.config import get_config

    primary = get_config().llm.provider          # loads .env as a side effect
    fallback = os.environ.get("ORION_LLM_FALLBACK_PROVIDER", "k2think")
    if fallback == primary:
        fallback = ""
    return primary, fallback


def model_label(provider: str) -> str:
    """What to call this model in the UI. Never flatters a fallback."""
    return "orionflow" if provider in OURS else f"fallback:{provider}"

CONVERSATION_SYSTEM = """You are OrionFlow, a mechanical design engineer talking \
an engineer through a part you just designed.

You have the part's Blueprint (its variables, feature tree and the assertions it \
was graded against) and the verification report from the geometry kernel. Ground \
every claim in those. Specifics only: name the variable, quote the measured \
number, cite the standard.

Rules that matter:
- If the report says a check failed, lead with that. Never describe a refused \
part as if it were fine.
- If something was not checked, say it was not checked. Do not infer that it passed.
- If you do not know a value, say so and ask, rather than inventing a number.
- Be brief. Two or three short paragraphs unless asked for more."""


def _looks_like_a_question(text: str) -> bool:
    """Route a turn to conversation rather than a rebuild.

    Cheap and explicit on purpose. The cost of the two mistakes is asymmetric:
    answering a design request with prose wastes a sentence, while silently
    rebuilding the part when the user only asked "why 6 mm?" throws away their
    model. So this leans towards conversation.
    """
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    openers = ("why", "what", "how", "explain", "is it", "are the", "does it",
               "can it", "should i", "tell me", "which", "who", "when",
               "would it", "will it", "do i")
    return t.startswith(openers)


class StudioAgent:
    """Owns the model clients. Cheap to construct, so the API can hold one."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    def _client(self, provider: str):
        if provider not in self._clients:
            from orion_agent.harness.llm import get_llm_client
            from orion_agent.shared.config import get_config

            cfg = get_config()
            self._clients[provider] = get_llm_client(provider, config=cfg)
        return self._clients[provider]

    def health(self) -> dict:
        from app.services.blueprint_service import BUILDER_MODE, freecad_available
        from orion_agent.shared.config import get_config

        cfg = get_config()
        primary, fallback = _providers()
        # In modal mode FreeCAD lives in another container, so this process
        # not having it is expected and must not read as "no kernel".
        builder_ok = BUILDER_MODE == "modal" or freecad_available()
        return {
            "provider": primary,
            "fallback": fallback,
            "serving_our_model": primary in OURS,
            "model": cfg.llm.model,
            "endpoint": cfg.llm.base_url,
            "builder": "freecad" if builder_ok else "unavailable",
            "builder_mode": BUILDER_MODE,
        }

    # ------------------------------------------------------------------ #
    def _complete(self, messages, on_event: EventSink, channel: str,
                  max_tokens: Optional[int] = None):
        """Stream a completion, falling back once, reporting which model ran.

        Returns ``(response, model_label)``. ``model_label`` is "orionflow" for
        our own model and "fallback:<provider>" otherwise; callers must surface
        it rather than hide it.
        """
        def emit_token(kind: str, text: str) -> None:
            if on_event and text:
                on_event(kind if kind == "thinking" else channel, {"text": text})

        for provider in _providers():
            if not provider:
                continue
            label = model_label(provider)
            try:
                client = self._client(provider)
            except Exception as exc:  # noqa: BLE001 — unknown/misconfigured provider
                logger.warning("studio_provider_init_failed",
                               provider=provider, error=str(exc))
                continue

            if on_event:
                on_event("model", {"model": label, "provider": provider})
            resp = client.chat_stream(messages, on_token=emit_token,
                                      max_tokens=max_tokens)
            # Transport failures come back as content, not exceptions, so the
            # loop never wedges on a dead endpoint. Detect and move on.
            failed = (resp.finish_reason == "error"
                      or resp.content.startswith("[vllm transport error"))
            if not failed:
                return resp, label
            logger.warning("studio_provider_failed",
                           provider=provider, detail=resp.content[:200])

        return None, ""

    # ------------------------------------------------------------------ #
    def design(self, prompt: str, on_event: EventSink = None) -> dict:
        """Prompt → Blueprint → geometry → verdict."""
        from orion.pack_sft import SYSTEM_PROMPT
        from orion_agent.harness.llm.base import LLMMessage
        from app.services import blueprint_service

        messages = [LLMMessage.system(SYSTEM_PROMPT), LLMMessage.user(prompt)]

        if on_event:
            on_event("phase", {"phase": "reasoning"})
        resp, label = self._complete(messages, on_event, "answer",
                                     max_tokens=4096)
        if resp is None:
            return {"success": False, "model": "",
                    "error": "no model is reachable — the inference endpoint "
                             "is down and the fallback also failed",
                    "verification": {}, "files": {}}

        completion = resp.content
        if on_event:
            on_event("phase", {"phase": "building"})

        try:
            bundle = blueprint_service.build_from_completion(completion)
        except blueprint_service.BlueprintBuildError as exc:
            # The model answered but not with a Blueprint. That is a model
            # failure and must read as one — not as a kernel error.
            return {"success": False, "model": label, "error": str(exc),
                    "raw_completion": completion[:4000],
                    "verification": {}, "files": {}}

        bundle["model"] = label
        bundle["thinking"] = resp.thinking or bundle.get("thinking", "")
        bundle["prompt"] = prompt
        if on_event:
            on_event("built", {
                "success": bundle["success"],
                "files": bundle["files"],
                "stats": bundle["stats"],
                "error": bundle["error"],
            })
            on_event("verification", bundle.get("verification") or {})
        return bundle

    # ------------------------------------------------------------------ #
    def explain(self, prompt: str, part: Optional[dict] = None,
                history: Optional[list[dict]] = None,
                on_event: EventSink = None) -> dict:
        """Answer a question about the current part, grounded in its report."""
        from orion_agent.harness.llm.base import LLMMessage

        messages = [LLMMessage.system(CONVERSATION_SYSTEM)]

        if part:
            messages.append(LLMMessage.user(_part_context(part)))
            messages.append(LLMMessage.assistant(
                "Understood — I have the Blueprint and the verification report "
                "for this part in front of me."))

        for turn in (history or [])[-6:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if content and role in ("user", "assistant"):
                messages.append(LLMMessage(role, content))

        messages.append(LLMMessage.user(prompt))

        resp, label = self._complete(messages, on_event, "answer",
                                     max_tokens=1024)
        if resp is None:
            return {"success": False, "model": "",
                    "answer": "", "error": "no model is reachable"}
        return {"success": True, "model": label,
                "answer": resp.content.strip(), "thinking": resp.thinking,
                "error": None}


def _part_context(part: dict) -> str:
    """Everything the assistant is allowed to claim about the current part."""
    import json

    lines = ["Here is the part currently open in the studio.", ""]
    if part.get("prompt"):
        lines.append(f"It was asked for as: {part['prompt']}")
    if part.get("part_class"):
        lines.append(f"Part class: {part['part_class']}")
    if part.get("variables"):
        lines.append(f"Variables: {json.dumps(part['variables'])}")

    stats = part.get("stats") or {}
    if stats:
        lines.append(
            f"Measured: volume {stats.get('volume_mm3')} mm^3, "
            f"bounding box {stats.get('bbox_mm')} mm, "
            f"watertight={stats.get('watertight')}")

    report = part.get("verification") or {}
    if report:
        lines.append(f"Verification verdict: {report.get('verdict')}")
        for c in report.get("checks", []):
            lines.append(f"  [{c.get('status')}] {c.get('label')}: {c.get('detail')}")
        if not report.get("checks"):
            lines.append("  (no checks were run — nothing here is proven)")

    bp = part.get("blueprint") or {}
    if bp.get("design_plan"):
        lines.append(f"Design plan: {json.dumps(bp['design_plan'])[:1500]}")
    return "\n".join(lines)


_agent: Optional[StudioAgent] = None


def get_studio_agent() -> StudioAgent:
    global _agent
    if _agent is None:
        _agent = StudioAgent()
    return _agent
