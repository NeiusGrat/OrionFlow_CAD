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

#: Which model DESIGNS. Named explicitly rather than inherited from
#: ``config.llm.model``, because that value is what the agent loop and the
#: conversation use, and those need the base adapter. Leaving the design path to
#: inherit it means a deployment that correctly sets the base model for the
#: copilot silently generates geometry with untuned weights — a failure that
#: looks like the fine-tune regressing rather than like a config error.
DESIGN_MODEL = os.environ.get("ORION_DESIGN_MODEL", "orionflow")

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

    primary = get_config().llm.provider  # loads .env as a side effect
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


#: How many tool rounds a conversation turn may take before it must answer.
#: Three is enough to look something up, follow one cross-reference, and reply;
#: more usually means the model is circling rather than converging.
KNOWLEDGE_TOOL_ROUNDS = max(1, int(os.environ.get("ORION_KNOWLEDGE_ROUNDS", "3")))

_KNOWLEDGE_REGISTRY: Any = None
_KNOWLEDGE_TRIED = False


def _knowledge_registry():
    """The FreeCAD-free tool surface, built once, or None if unavailable.

    Cached because building it parses the knowledge JSON, and returned as None
    on failure so a missing asset costs the conversation its citations rather
    than the whole answer.
    """
    global _KNOWLEDGE_REGISTRY, _KNOWLEDGE_TRIED
    if not _KNOWLEDGE_TRIED:
        _KNOWLEDGE_TRIED = True
        try:
            from orion_agent.harness.tools.registry import (
                build_knowledge_registry,
            )

            _KNOWLEDGE_REGISTRY = build_knowledge_registry()
            logger.info(
                "studio_knowledge_tools_ready", tools=len(_KNOWLEDGE_REGISTRY.names())
            )
        except Exception as exc:  # noqa: BLE001 — grounding is optional
            logger.warning("studio_knowledge_tools_unavailable", error=str(exc))
            _KNOWLEDGE_REGISTRY = None
    return _KNOWLEDGE_REGISTRY


#: Outcome ranking, worst to best. A repair round can make things worse (a
#: second attempt that fails to parse), so the loop keeps the best result rather
#: than whatever came last.
_NOTHING, _BUILT_UNVERIFIED, _VERIFIED = 1, 2, 3


def _rank(bundle: dict) -> int:
    if not bundle:
        return 0
    if (bundle.get("verification") or {}).get("verdict") == "verified":
        return _VERIFIED
    if bundle.get("success"):
        return _BUILT_UNVERIFIED
    return _NOTHING


def _repair_turn(base: list, completion: str, diagnosis: str) -> list:
    """The repair conversation: the original ask, the failed attempt, the reason.

    Delegates the shape to ``repair_loop.build_repair_messages`` so the studio
    and the eval harness ask for a fix in exactly the same words — otherwise the
    VERIFIED @1 repair number measured offline would not describe what a user
    gets.
    """
    from orion.repair_loop import build_repair_messages
    from orion_agent.harness.llm.base import LLMMessage

    wire = build_repair_messages(
        [{"role": m.role, "content": m.content} for m in base], completion, diagnosis
    )
    return [LLMMessage(m["role"], m["content"]) for m in wire]


def _classify_failure(bundle: dict) -> tuple[str, dict]:
    """``(error, verdict)`` in the vocabulary ``orion.repair_loop`` expects.

    The eval harness classifies failures as ``freeze:``/``build:``/``timeout:``/
    ``precondition:``/``assert:`` and the diagnosis switches on that prefix, so
    the studio has to speak the same language to reuse it. Returns the verdict
    shape ``diagnose`` reads as well, since the studio bundle spells the same
    facts differently.
    """
    error = str(bundle.get("error") or "")
    rows = bundle.get("assertions") or []
    failed_pre = [
        {"id": r.get("id"), "target": r.get("target")}
        for r in rows
        if r.get("kind") == "precondition" and not r.get("passed")
    ]
    verdict = {"assertions": rows, "failed_preconditions": failed_pre}

    if error.startswith("blueprint rejected:"):
        return f"freeze: {error.split(':', 1)[1].strip()}", verdict
    if error.startswith("blueprint could not be resolved:"):
        return f"freeze: {error.split(':', 1)[1].strip()}", verdict
    if "did not converge" in error:
        return "timeout: kernel exceeded the build budget", verdict
    if failed_pre:
        return ("precondition: " + ",".join(str(p["id"]) for p in failed_pre)), verdict
    bad = [str(r.get("id")) for r in rows if not r.get("passed")]
    if bad:
        return "assert: " + ",".join(bad), verdict
    if error:
        return f"build: {error}", verdict
    return "build: the part could not be verified", verdict


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
    openers = (
        "why",
        "what",
        "how",
        "explain",
        "is it",
        "are the",
        "does it",
        "can it",
        "should i",
        "tell me",
        "which",
        "who",
        "when",
        "would it",
        "will it",
        "do i",
    )
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
    def _complete(
        self,
        messages,
        on_event: EventSink,
        channel: Optional[str] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        tools: Optional[list[dict]] = None,
    ):
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

        ``tools`` is passed to the backend when supplied. Only the conversation
        path uses it: the design path must stay byte-identical to training, and
        a tool schema in that prompt is exactly the drift this module exists to
        prevent.

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
                logger.warning(
                    "studio_provider_init_failed", provider=provider, error=str(exc)
                )
                continue

            if on_event:
                on_event("model", {"model": label, "provider": provider})
            kw = {"model": model} if model else {}
            if tools:
                kw["tools"] = tools
            resp = client.chat_stream(
                messages, on_token=emit_token, max_tokens=max_tokens, **kw
            )
            # Transport failures come back as content, not exceptions, so the
            # loop never wedges on a dead endpoint. Detect and move on.
            failed = resp.finish_reason == "error" or resp.content.startswith(
                "[vllm transport error"
            )
            if not failed:
                return resp, label
            logger.warning(
                "studio_provider_failed", provider=provider, detail=resp.content[:200]
            )

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
        from orion import calc, repair_loop
        from orion.pack_sft import SYSTEM_PROMPT
        from orion_agent.harness.llm.base import LLMMessage
        from app.services import blueprint_service, design_narrative

        def step(
            sid: str,
            label: str,
            status: str = "active",
            detail: str = "",
            items: Optional[list] = None,
        ) -> None:
            if on_event:
                on_event(
                    "step",
                    {
                        "id": sid,
                        "label": label,
                        "status": status,
                        "detail": detail,
                        "items": items or [],
                    },
                )

        # Turn 1 is the ONLY turn that must match training byte for byte, so it
        # is built from these two messages and nothing else, every time. Repair
        # turns are rebuilt from this same pair plus the failed attempt and its
        # diagnosis — never by appending to a growing history, which would put a
        # second user turn in front of the model on attempt 3 and stop looking
        # like the repair records at all.
        base_messages = [LLMMessage.system(SYSTEM_PROMPT), LLMMessage.user(prompt)]
        messages = list(base_messages)

        # A failed attempt is not resampled blind. The verifier already knows
        # exactly what went wrong — which assertion missed, by how much, and
        # which feature's own volume accounts for the gap — so the next turn
        # gets that as a diagnosis. Blind resampling was the previous behaviour
        # and it cannot fix a wrong derivation: the same prompt draws the same
        # reasoning. The measured evidence is what changes the answer.
        bundle: dict = {}
        best: dict = {}
        features: list = []
        best_features: list = []
        for attempt in range(1, DESIGN_ATTEMPTS + 1):
            again = attempt > 1
            step(
                "understand",
                "Understanding the request",
                "active",
                f"repair attempt {attempt}" if again else "",
            )
            if on_event:
                on_event("phase", {"phase": "reasoning"})
            # channel=None: emit no raw tokens. See _complete for why.
            resp, label = self._complete(
                messages, on_event, channel=None, max_tokens=4096, model=DESIGN_MODEL
            )
            if resp is None:
                # An endpoint that dies on the repair turn must not cost the
                # user a part that already built on the first one. Same rule as
                # the parse-failure path below: keep the best result, report
                # only when there is nothing to keep.
                if best:
                    break
                step(
                    "understand",
                    "Understanding the request",
                    "fail",
                    "no model is reachable",
                )
                return {
                    "success": False,
                    "model": "",
                    "error": "no model is reachable — the inference "
                    "endpoint is down and the fallback also "
                    "failed",
                    "verification": {},
                    "files": {},
                }

            completion = resp.content

            # ---- interpretation: facts straight off the parsed Blueprint ----
            try:
                _, payload = blueprint_service.parse_completion(completion)
            except blueprint_service.BlueprintBuildError as exc:
                # The model answered, but not with a Blueprint. That is a model
                # failure and must read as one — not as a kernel error.
                if attempt < DESIGN_ATTEMPTS:
                    step(
                        "understand",
                        "Understanding the request",
                        "active",
                        "no Blueprint returned — asking again with the reason",
                    )
                    messages = _repair_turn(
                        base_messages,
                        completion,
                        repair_loop.diagnose(None, f"parse: {exc}"),
                    )
                    continue
                if best:
                    break
                step(
                    "understand",
                    "Understanding the request",
                    "fail",
                    "the model did not return a Blueprint",
                )
                return {
                    "success": False,
                    "model": label,
                    "error": str(exc),
                    "raw_completion": completion[:4000],
                    "verification": {},
                    "files": {},
                }

            part_class = payload.get("part_class", "")
            variables = payload.get("variables", {}) or {}
            template = payload.get("template", {}) or {}

            step(
                "understand",
                "Understanding the request",
                "done",
                design_narrative._readable_class(part_class),
            )
            step(
                "dimensions",
                "Solving dimensions",
                "done",
                f"{len(variables)} parameters",
                [f"{k} = {v}" for k, v in variables.items()],
            )

            features = [
                f
                for f in (template.get("features") or [])
                if f.get("type") not in ("Body", "Sketch")
            ]
            step(
                "build",
                "Building the model",
                "active",
                f"{len(features)} features",
                [f.get("rationale") or f.get("id", "") for f in features],
            )
            if on_event:
                on_event("phase", {"phase": "building"})

            bundle = blueprint_service.build_from_payload(payload)
            bundle["model"] = label
            bundle["thinking"] = resp.thinking or bundle.get("thinking", "")
            bundle["prompt"] = prompt
            bundle["attempts"] = attempt

            # The model states a number at the end of its derivation and never
            # evaluates it — measured across the held-out set, that number
            # disagrees with the model's OWN expression in every single case,
            # including parts that go on to verify. The expression is the
            # contract; the prose is decoration. Recompute it here so the raw
            # derivation is never shown to a user as if it were arithmetic.
            bundle["volume_claim"] = calc.check_stated_volume(
                payload, bundle["thinking"]
            )

            # Keep the best result seen, not the last one. A later attempt that
            # fails to parse must not throw away an earlier part that built —
            # geometry the user can look at beats nothing, even unverified.
            if _rank(bundle) > _rank(best):
                best, best_features = bundle, features

            if _rank(bundle) == _VERIFIED:
                break

            if attempt < DESIGN_ATTEMPTS:
                error, verdict = _classify_failure(bundle)
                diagnosis = repair_loop.diagnose(
                    payload, error, verdict=verdict, measured=bundle.get("measured")
                )
                step(
                    "build",
                    "Building the model",
                    "active",
                    f"{_short(error)} — repairing",
                )
                if on_event:
                    # Surfaced, not hidden: a part that needed a repair round is
                    # a different claim from one that verified first time.
                    on_event(
                        "repair",
                        {"attempt": attempt, "error": error, "diagnosis": diagnosis},
                    )
                messages = _repair_turn(base_messages, completion, diagnosis)
                continue

        bundle = best or bundle
        features = best_features or features
        # How many attempts the turn actually cost, not how many the surviving
        # bundle happened to be produced on. When every attempt fails at the
        # same rank the first one is kept, and reporting its ``attempts`` of 1
        # hides the repair round entirely from anything counting them.
        if bundle:
            bundle["attempts"] = attempt

        if not bundle.get("success"):
            step(
                "build",
                "Building the model",
                "fail",
                _short(bundle.get("error")) or "the build failed",
            )
            if on_event:
                on_event(
                    "built",
                    {
                        "success": False,
                        "files": {},
                        "stats": None,
                        "error": bundle.get("error"),
                    },
                )
            return bundle

        step("build", "Building the model", "done", f"{len(features)} features")
        if on_event:
            on_event(
                "built",
                {
                    "success": True,
                    "files": bundle["files"],
                    "stats": bundle["stats"],
                    "error": None,
                },
            )

        report = bundle.get("verification") or {}
        checks = report.get("checks") or []
        step(
            "verify",
            "Running verification",
            "done" if report.get("verdict") == "verified" else "fail",
            f"{len(checks)} checks",
            [c.get("label", "") for c in checks],
        )
        if on_event:
            on_event("verification", report)

        # The readable account of the design. Derived, never authored — see
        # design_narrative for why a second model pass is the wrong tool.
        bundle["narrative"] = design_narrative.build(bundle, prompt=prompt)
        if on_event and bundle["narrative"]:
            on_event("narrative", bundle["narrative"])
        return bundle

    # ------------------------------------------------------------------ #
    def explain(
        self,
        prompt: str,
        part: Optional[dict] = None,
        history: Optional[list[dict]] = None,
        on_event: EventSink = None,
    ) -> dict:
        """Answer a question about the current part, grounded in its report."""
        from orion_agent.harness.llm.base import LLMMessage

        messages = [LLMMessage.system(CONVERSATION_SYSTEM)]

        if part:
            messages.append(LLMMessage.user(_part_context(part)))
            messages.append(
                LLMMessage.assistant(
                    "Understood — I have the Blueprint and the verification report "
                    "for this part in front of me."
                )
            )

        for turn in (history or [])[-6:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if content and role in ("user", "assistant"):
                messages.append(LLMMessage(role, content))

        messages.append(LLMMessage.user(prompt))

        # Knowledge tools, conversation side only. These are the twelve that
        # touch no geometry — ISO/DIN lookups, the NASA requirement graph,
        # materials, sheet-metal DFM — so they need no FreeCAD and can run in
        # the cloud. Quoting a real clause beats paraphrasing one from memory,
        # and the citation is checkable.
        registry = _knowledge_registry()
        schemas = registry.schemas() if registry else None

        used: list[str] = []
        for _round in range(KNOWLEDGE_TOOL_ROUNDS):
            resp, label = self._complete(
                messages,
                on_event,
                "answer",
                max_tokens=1024,
                model=CONVERSATION_MODEL,
                tools=schemas,
            )
            if resp is None:
                return {
                    "success": False,
                    "model": "",
                    "answer": "",
                    "error": "no model is reachable",
                }
            if not resp.tool_calls:
                break

            messages.append(
                LLMMessage.assistant(resp.content, tool_calls=resp.tool_calls)
            )
            for call in resp.tool_calls:
                result = registry.execute(call.name, call.arguments)
                used.append(call.name)
                if on_event:
                    # Shown, not hidden: an answer backed by a lookup is a
                    # different claim from one the model produced unaided.
                    on_event(
                        "tool",
                        {
                            "name": call.name,
                            "arguments": call.arguments,
                            "ok": result.ok,
                        },
                    )
                messages.append(LLMMessage.tool(result.content, call.id, call.name))
        else:
            # Budget spent and still calling tools — answer with what it has
            # rather than looping.
            resp, label = self._complete(
                messages, on_event, "answer", max_tokens=1024, model=CONVERSATION_MODEL
            )
            if resp is None:
                return {
                    "success": False,
                    "model": "",
                    "answer": "",
                    "error": "no model is reachable",
                }

        answer = _strip_blueprint(resp.content)
        if not answer:
            # The model answered with a Blueprint instead of prose. Say so
            # rather than pasting JSON into the conversation.
            return {
                "success": False,
                "model": label,
                "answer": "",
                "error": "the model returned a design instead of an "
                "answer — try rephrasing as a question",
            }
        return {
            "success": True,
            "model": label,
            "answer": answer,
            "thinking": resp.thinking,
            "tools_used": used,
            "error": None,
        }


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
            f"watertight={stats.get('watertight')}"
        )

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
