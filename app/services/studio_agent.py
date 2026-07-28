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


#: Which model answers questions. Our LoRA is trained to reply to everything
#: with a Blueprint, so it is the wrong tool for conversation; the untouched
#: base is served alongside it on the same endpoint for exactly this.
CONVERSATION_MODEL = os.environ.get("ORION_CONVERSATION_MODEL", "orionflow-base")

#: How many times to draw a design before giving up. Two by default: one
#: resample recovers most static-check misses, and a third rarely adds anything
#: a user is still waiting for.
DESIGN_ATTEMPTS = max(1, int(os.environ.get("ORION_DESIGN_ATTEMPTS", "2")))


def _short(msg: Optional[str], limit: int = 70) -> str:
    """First line of an error, trimmed — step details are one line of UI."""
    if not msg:
        return ""
    first = str(msg).strip().splitlines()[0].strip()
    return first if len(first) <= limit else first[: limit - 1] + "…"


def _strip_blueprint(text: str) -> str:
    """Prose only. Returns "" if the reply was really a Blueprint.

    Belt and braces behind CONVERSATION_MODEL: whatever answers, raw JSON must
    never reach the conversation. Showing it is what made the panel look like a
    code generator in the first place.
    """
    body = text.strip()
    if "</think>" in body:
        body = body.rpartition("</think>")[2].strip()
    if "```" in body:
        # Drop fenced blocks; keep the prose around them.
        parts = body.split("```")
        body = " ".join(p for i, p in enumerate(parts) if i % 2 == 0).strip()
    # A reply that is mostly a JSON object is a design, not an answer.
    brace = body.find("{")
    if brace != -1 and ('"part_class"' in body or '"template"' in body):
        body = body[:brace].strip()
    return body


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
    def _complete(self, messages, on_event: EventSink,
                  channel: Optional[str] = None,
                  max_tokens: Optional[int] = None,
                  model: Optional[str] = None):
        """Stream a completion, falling back once, reporting which model ran.

        ``channel`` is the event name for answer tokens, or None to emit no
        tokens at all. The design path passes None deliberately: the adapter
        decides "is this thinking?" by looking for a ``<think>`` **opening**
        tag, and the model never emits one (the chat template does not inject
        it, by design — see fine_tuning/orionflow_chatml.jinja). So every token
        classifies as an answer, and streaming them puts the raw derivation,
        the stray ``</think>`` and the entire Blueprint JSON on screen as if it
        were prose. Progress on that path comes from ``step`` events, which
        report real stages instead.

        Returns ``(response, model_label)``. ``model_label`` is "orionflow" for
        our own model and "fallback:<provider>" otherwise; callers must surface
        it rather than hide it.
        """
        def emit_token(kind: str, text: str) -> None:
            if on_event and text and channel:
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
            kw = {"model": model} if model else {}
            resp = client.chat_stream(messages, on_token=emit_token,
                                      max_tokens=max_tokens, **kw)
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
        """Prompt → Blueprint → geometry → verdict.

        Emits ``step`` events as each stage genuinely completes. They are
        derived from real state — the parsed part class, the actual feature
        list, the checks that ran — never from a timer, so a stalled stage
        looks stalled instead of animating cheerfully towards a result that
        will not arrive.
        """
        from orion.pack_sft import SYSTEM_PROMPT
        from orion_agent.harness.llm.base import LLMMessage
        from app.services import blueprint_service, design_narrative

        def step(sid: str, label: str, status: str = "active",
                 detail: str = "", items: Optional[list] = None) -> None:
            if on_event:
                on_event("step", {"id": sid, "label": label, "status": status,
                                  "detail": detail, "items": items or []})

        messages = [LLMMessage.system(SYSTEM_PROMPT), LLMMessage.user(prompt)]

        # Sampling is stochastic and a fraction of samples miss for reasons a
        # second draw fixes — an unused variable the static checker rejects, a
        # truncated object. Resampling is honest (it is the same model, asked
        # again) and cheap next to the build, so a recoverable miss does not
        # become a dead end. It never masks a failure: if every attempt misses,
        # the last real error is what gets reported.
        bundle: dict = {}
        features: list = []
        for attempt in range(1, DESIGN_ATTEMPTS + 1):
            again = attempt > 1
            step("understand", "Understanding the request", "active",
                 f"attempt {attempt}" if again else "")
            if on_event:
                on_event("phase", {"phase": "reasoning"})
            # channel=None: emit no raw tokens. See _complete for why.
            resp, label = self._complete(messages, on_event, channel=None,
                                         max_tokens=4096)
            if resp is None:
                step("understand", "Understanding the request", "fail",
                     "no model is reachable")
                return {"success": False, "model": "",
                        "error": "no model is reachable — the inference "
                                 "endpoint is down and the fallback also "
                                 "failed",
                        "verification": {}, "files": {}}

            completion = resp.content

            # ---- interpretation: facts straight off the parsed Blueprint ----
            try:
                _, payload = blueprint_service.parse_completion(completion)
            except blueprint_service.BlueprintBuildError as exc:
                # The model answered, but not with a Blueprint. That is a model
                # failure and must read as one — not as a kernel error.
                if attempt < DESIGN_ATTEMPTS:
                    step("understand", "Understanding the request", "active",
                         "no Blueprint returned — resampling")
                    continue
                step("understand", "Understanding the request", "fail",
                     "the model did not return a Blueprint")
                return {"success": False, "model": label, "error": str(exc),
                        "raw_completion": completion[:4000],
                        "verification": {}, "files": {}}

            part_class = payload.get("part_class", "")
            variables = payload.get("variables", {}) or {}
            template = payload.get("template", {}) or {}

            step("understand", "Understanding the request", "done",
                 design_narrative._readable_class(part_class))
            step("dimensions", "Solving dimensions", "done",
                 f"{len(variables)} parameters",
                 [f"{k} = {v}" for k, v in variables.items()])

            features = [f for f in (template.get("features") or [])
                        if f.get("type") not in ("Body", "Sketch")]
            step("build", "Building the model", "active",
                 f"{len(features)} features",
                 [f.get("rationale") or f.get("id", "") for f in features])
            if on_event:
                on_event("phase", {"phase": "building"})

            bundle = blueprint_service.build_from_payload(payload)
            bundle["model"] = label
            bundle["thinking"] = resp.thinking or bundle.get("thinking", "")
            bundle["prompt"] = prompt
            bundle["attempts"] = attempt

            if bundle.get("success"):
                break

            if attempt < DESIGN_ATTEMPTS:
                step("build", "Building the model", "active",
                     _short(bundle.get("error")) + " — resampling")
                continue

            step("build", "Building the model", "fail",
                 _short(bundle.get("error")) or "the build failed")
            if on_event:
                on_event("built", {"success": False, "files": {},
                                   "stats": None, "error": bundle.get("error")})
            return bundle

        step("build", "Building the model", "done", f"{len(features)} features")
        if on_event:
            on_event("built", {
                "success": True,
                "files": bundle["files"],
                "stats": bundle["stats"],
                "error": None,
            })

        report = bundle.get("verification") or {}
        checks = report.get("checks") or []
        step("verify", "Running verification",
             "done" if report.get("verdict") == "verified" else "fail",
             f"{len(checks)} checks",
             [c.get("label", "") for c in checks])
        if on_event:
            on_event("verification", report)

        # The readable account of the design. Derived, never authored — see
        # design_narrative for why a second model pass is the wrong tool.
        bundle["narrative"] = design_narrative.build(bundle, prompt=prompt)
        if on_event and bundle["narrative"]:
            on_event("narrative", bundle["narrative"])
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
                                     max_tokens=1024,
                                     model=CONVERSATION_MODEL)
        if resp is None:
            return {"success": False, "model": "",
                    "answer": "", "error": "no model is reachable"}

        answer = _strip_blueprint(resp.content)
        if not answer:
            # The model answered with a Blueprint instead of prose. Say so
            # rather than pasting JSON into the conversation.
            return {"success": False, "model": label, "answer": "",
                    "error": "the model returned a design instead of an "
                             "answer — try rephrasing as a question"}
        return {"success": True, "model": label,
                "answer": answer, "thinking": resp.thinking, "error": None}


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
