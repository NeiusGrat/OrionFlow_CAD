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
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

EventSink = Optional[Callable[[str, dict], None]]

#: Providers that talk to an endpoint WE run — an OpenAI-compatible vLLM
#: server. This is a *transport* fact and nothing more: it says the API accepts
#: ``model=`` naming one of several adapters served side by side. It says
#: nothing about who trained the weights behind it.
OUR_ENDPOINT = ("vllm", "openai")


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

#: The adapter names our endpoint serves when the weights behind it are OURS:
#: the LoRA and the untouched base alongside it. Overridable because the served
#: names are a deployment decision, but the distinction they encode is not.
#:
#: A stock open model behind our own vLLM — a Modal-managed Qwen, say — makes
#: the transport ours and the training somebody else's, and that gap is exactly
#: where the two used to be conflated. Three things turn on it: the label the
#: UI shows, ``serving_our_model`` in health, and the gate that lets a model
#: author a Blueprint unaided. Only the LoRA was ever trained for the last one;
#: a stock model asked to try spends two sampling rounds arriving at "no
#: Blueprint JSON in completion", which is the outcome the deterministic path
#: was built to replace. Sending an adapter name to an endpoint that does not
#: serve it is a 404 on top.
OUR_ADAPTERS = frozenset(
    name.strip()
    for name in os.environ.get(
        "ORION_OUR_ADAPTERS", "orionflow,orionflow-base"
    ).split(",")
    if name.strip()
)


def serving_fine_tune(provider: str) -> bool:
    """Whether ``provider`` is serving weights we trained.

    Both halves are required, and neither implies the other: our endpoint
    serving stock Qwen is not our model, and our adapter name pointed at
    somebody else's API is not even reachable.
    """
    return provider in OUR_ENDPOINT and DESIGN_MODEL in OUR_ADAPTERS


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
    """What to call this model in the UI. Never flatters a fallback.

    A stock model on our own endpoint is named for what it is rather than
    called a fallback: it is the configured primary, so "fallback:" would be
    as wrong as "orionflow". Only the fine-tune earns our name.
    """
    if serving_fine_tune(provider):
        return "orionflow"
    if provider in OUR_ENDPOINT:
        return DESIGN_MODEL
    return f"fallback:{provider}"


#: Providers that just failed at the transport, and when to trust them again.
#:
#: Rediscovering a dead endpoint costs a full connect timeout — measured 21.4s
#: against the torn-down GPU — and the interview's two calls plus every design
#: draw each pay it, on every request. That is a minute of silence per turn,
#: which reads as a hung product rather than as a failed provider.
#:
#: A provider on cooldown is moved to the *back* of the queue rather than
#: removed from it. If a blip marks the only reachable model down, trying it and
#: failing is still better than reporting that no model exists.
_DOWN: dict[str, float] = {}
PROVIDER_COOLDOWN = float(os.environ.get("ORION_PROVIDER_COOLDOWN", "120"))


def _is_down(provider: str) -> bool:
    return _DOWN.get(provider, 0.0) > time.time()


def _mark_down(provider: str, why: str = "") -> None:
    _DOWN[provider] = time.time() + PROVIDER_COOLDOWN
    logger.warning(
        "provider_marked_down",
        provider=provider,
        cooldown_s=PROVIDER_COOLDOWN,
        error=why[:200],
    )


def _mark_up(provider: str) -> None:
    if _DOWN.pop(provider, None) is not None:
        logger.info("provider_recovered", provider=provider)


def _in_health_order(providers) -> list[str]:
    """Reachable providers first, then those on cooldown. Never empty-handed."""
    named = [p for p in providers if p]
    return [p for p in named if not _is_down(p)] + [p for p in named if _is_down(p)]


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


#: Appended when the part's own geometry is reachable as tools.
#:
#: The summary in the context is a précis — counts, a bounding box, a verdict.
#: The tools reach the build itself: every face and its surface type, every
#: feature's parameters and the expression that produced them, real distances
#: between named elements. Without this paragraph the model answers from the
#: précis and never calls them, which is the same as not having them.
INSPECTION_BRIEF = """
You can inspect the built part directly rather than reasoning from the summary \
above. Use `list_objects` to see what it is made of, `inspect_topology` for real \
face/edge counts, surface types and the bounding box (of the whole body, or of \
one named feature), `get_parameters` for a feature's dimensions together with \
the expression each one was derived from, `get_featuregraph` for how it was \
built, and `measure` for the distance between two named elements.

Check before you claim. A quantitative statement about this part — how many \
holes, how thick a wall, how far apart two faces are — should come from a tool \
call, not from the summary and not from memory.

`measure` tells you whether its answer is exact or an estimate. When it says \
the result is a bounding-box lower bound, report it as a bound, not as the \
distance."""


#: What the assistant is being asked to look at.
#:
#: A lens is appended to the *conversation* system prompt only. The design role
#: is left exactly as the fine-tune was trained and graded — see the module
#: docstring — so switching to sheet-metal review changes what gets discussed,
#: never how geometry is authored.
#:
#: Each brief names the specific failures that process actually has. "Consider
#: manufacturability" produces a paragraph of generalities; "say which face has
#: no tool access" produces an answer an engineer can act on.
LENS_BRIEFS = {
    "modeling": "",
    "dfm": """
Review this part for manufacturability. Name the process you are assuming and \
why it suits the geometry, then work through the features that would give that \
process trouble. If a different process would be markedly cheaper or more \
robust at this geometry, say so and say at roughly what quantity the crossover \
sits.""",
    "dfm_3d_printing": """
Review this part for fused-deposition and resin printing. Work through: build \
orientation and what it costs in surface finish; overhangs past roughly 45° \
and which faces they land on; where supports would have to touch a functional \
surface; minimum wall and pin thickness against a typical 0.4 mm nozzle; holes \
printed vertically coming out undersize and needing reaming; and layer \
adhesion where the load path crosses the layer lines. Anisotropy is the part \
engineers most often miss — if a feature is loaded across the layers, lead \
with that.""",
    "dfm_sheet_metal": """
Review this part as sheet metal. Work through: whether the geometry can be \
made from one flat blank at a constant thickness, and say plainly if it cannot; \
bend radii against material thickness (a rule of thumb of one thickness for \
soft aluminium, more for tempered); K-factor and how the flat pattern length \
follows from it; relief cuts at the ends of bends to stop tearing; hole and \
feature distance from a bend line, roughly 2.5× thickness plus the radius; and \
where a forming tool or a weld would be needed instead of a bend.""",
    "dfm_machining": """
Review this part for 3-axis milling and turning. Work through: how many setups \
it needs and what has to be re-fixtured between them; internal corner radii, \
which cannot be smaller than the cutter — call out any modelled sharp internal \
corner; pocket depth-to-width ratio against tool deflection and chatter; tool \
access to every surface you are asked to hold a tolerance on; thin walls that \
will chatter or spring; and drilled holes that are not a stock drill size. Say \
which dimensions are cheap to hold and which ones drive the price.""",
}


#: Refining an idea before there is anything to refine.
#:
#: The ordinary conversation prompt assumes a part exists and tells the model
#: to ground every claim in its report. With nothing open that instruction has
#: nothing to bind to, and the model either invents a part to describe or
#: refuses to engage. This replaces it for that case: the job is to turn a
#: sentence into a set of numbers somebody could actually build.
SCOPING_SYSTEM = """You are OrionFlow, a mechanical design engineer helping \
another engineer pin down a part before any geometry exists.

Nothing has been modelled yet. Your job is to get from a description to a \
specification: the dimensions that matter, the ones that follow from them, the \
material, the loads, and how it is going to be made and fixtured.

How to work:
- Lead with the specification you would commit to, as concrete numbers with the \
reasoning that produced them. A proposal an engineer can correct beats a list \
of questions.
- Where a number genuinely depends on something only they know — a mating part, \
a load, a bolt size — state the assumption you are making and flag it, rather \
than stopping.
- Name standards where a standard settles it: bearing series, thread pitch, \
sheet gauge, fits and tolerances.
- Ask at most one question, and only when the answer would change the geometry.
- Be brief. This is a working conversation, not a report.

When the specification is firm enough to build, say so plainly in one short \
sentence at the end."""


def lens_system(
    lens: Optional[str], has_part: bool = True, can_inspect: bool = False
) -> str:
    """The conversation system prompt for a lens.

    ``has_part`` picks the base: an open part is discussed against its own
    verification report, an empty studio is scoped from nothing.
    ``can_inspect`` says whether this turn can actually reach the geometry, and
    is claimed only when a bridge was built — promising tools that are not in
    the schema list is how a model ends up describing a call it never made.
    """
    base = CONVERSATION_SYSTEM if has_part else SCOPING_SYSTEM
    if can_inspect:
        base += "\n" + INSPECTION_BRIEF.strip()
    brief = LENS_BRIEFS.get((lens or "modeling").strip().lower(), "")
    return base + ("\n" + brief.strip() if brief.strip() else "")


#: How many tool rounds a conversation turn may take before it must answer.
#: Three is enough to look something up, follow one cross-reference, and reply;
#: more usually means the model is circling rather than converging.
KNOWLEDGE_TOOL_ROUNDS = max(1, int(os.environ.get("ORION_KNOWLEDGE_ROUNDS", "3")))

#: The same budget when the part's own geometry is reachable.
#:
#: Higher because inspection is inherently sequential: orient with
#: ``list_objects``, read the shape with ``inspect_topology``, then measure the
#: two elements that answer the question. That is already three rounds before a
#: word of the answer exists, so the knowledge budget would cut the model off
#: exactly when it was doing the checking it was asked to do.
INSPECTION_TOOL_ROUNDS = max(1, int(os.environ.get("ORION_INSPECTION_ROUNDS", "6")))

#: Completion budget for an answer.
#:
#: Sized for a model that derives before it replies. This was 1024, which a
#: reasoning model spends entirely on the derivation: measured on K2-Think-v2,
#: scoping a NEMA 23 mounting plate cost 2,048 tokens of thinking and returned
#: an empty answer, which ``_strip_blueprint`` then could not distinguish from a
#: Blueprint and reported as "the model returned a design instead of an answer"
#: — a truncation diagnosed as the wrong failure entirely. At 4096 the same
#: question answers in 8.8s. A model that replies directly is unaffected: this
#: is a ceiling, not a target.
ANSWER_TOKENS = int(os.environ.get("ORION_ANSWER_TOKENS", "4096"))

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


def _part_registry(request_id: str, part: Optional[dict]):
    """Knowledge tools *plus* inspection of the part actually open, or None.

    This is the boundary the studio never crossed: the harness' geometry tools
    were written against a live FreeCAD desktop, so a cloud session could look
    up a standard but could not go and look at its own part. It never needed a
    kernel — the build already wrote the topology record, and the Blueprint
    resolves without one. ``PartBridge`` serves both.

    Built per turn, never cached: the bridge is bound to one build, and a cached
    registry would answer one session's question with another session's
    geometry. Construction is a few dozen closures — the knowledge JSON is read
    inside the executors, not here.
    """
    from app.services.part_bridge import for_part

    bridge = for_part(request_id, part)
    if bridge is None:
        return None
    try:
        from orion_agent.harness.tools.registry import build_part_registry

        return build_part_registry(bridge)
    except Exception as exc:  # noqa: BLE001 — fall back to knowledge-only
        logger.warning("studio_part_tools_unavailable", error=str(exc))
        return None


def _with_provenance(payload: dict, request: str, chain: Any = None) -> dict:
    """Stamp the ledger into a model-authored payload, before it is frozen.

    The compiled path gets this from ``blueprint_gen``, which knows exactly
    which requirement produced which variable. Here nothing knows: the model
    emitted a dict of floats, and the only evidence available is whether the
    request contains the number. That is a weaker test and it is the honest one
    — see ``orion.provenance`` for what it will and will not credit.

    A reasoning chain, when one ran, overrides that test for the variables it
    derived. Those numbers came from a standard or a calculation and are
    genuinely accounted for even though the user never typed them; testing them
    against the request would report the derivation itself as an invention.
    """
    from orion import provenance as P

    variables = payload.get("variables")
    if not isinstance(variables, dict) or not variables:
        return payload

    derived: dict[str, str] = {}
    if chain is not None:
        rationale = getattr(chain, "rationale", {}) or {}
        for name in getattr(chain, "variables", {}) or {}:
            if name in variables:
                derived[name] = (
                    rationale.get(name)
                    or "derived by the reasoning chain from the stated duty"
                )

    plan = dict(payload.get("design_plan") or {})
    plan["provenance"] = P.classify(request, variables, derived=derived)

    # Feature obligations cannot be derived on this path, and the honest move is
    # to say so rather than to emit an empty list — which downstream is
    # indistinguishable from "the request asked for nothing".
    #
    # The compiled path derives obligations from typed requirements; a model
    # authoring a Blueprint from prose produces no requirements dict, so there
    # is nothing to compare the built solid against. It also authors its own
    # volume assertion, so a feature it silently dropped is missing from both
    # the geometry and the prediction and the two still agree — the exact shape
    # of the defect obligations exist to catch. Declared here, before the
    # freeze, so it is inside the hash like every other claim.
    plan["feature_verification"] = {
        "available": False,
        "path": "model_authored",
        "reason": "this design was authored by a model from prose rather than "
        "compiled from typed requirements, so no feature obligations exist and "
        "nothing here can confirm that the features you asked for are present",
    }
    payload["design_plan"] = plan
    return payload


#: Outcome ranking, worst to best. A repair round can make things worse (a
#: second attempt that fails to parse), so the loop keeps the best result rather
#: than whatever came last.
#:
#: ``_UNSOURCED`` sits below ``_VERIFIED`` because a part whose dimensions
#: nobody accounted for is a weaker result — but above ``_BUILT_UNVERIFIED``,
#: and terminal, because resampling cannot fix it. A dimension the request never
#: gave will not be given by drawing again; the second draw would simply invent
#: a different number, and might invent one that happens to match a numeral in
#: the request and grade better for it.
_NOTHING, _BUILT_UNVERIFIED, _UNSOURCED, _VERIFIED = 1, 2, 3, 4


def _rank(bundle: dict) -> int:
    if not bundle:
        return 0
    verdict = (bundle.get("verification") or {}).get("verdict")
    if verdict == "verified":
        return _VERIFIED
    if verdict == "unsourced":
        return _UNSOURCED
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


# --------------------------------------------------------------------------- #
# the proposal: a design that exists before it is a solid
# --------------------------------------------------------------------------- #
def _emit_step(
    on_event: EventSink,
    sid: str,
    label: str,
    status: str = "active",
    detail: str = "",
    items: Optional[list] = None,
) -> None:
    """One stage of a turn, reported when it genuinely happened.

    Steps are keyed by id and replace in place on the client, so re-emitting
    one with a new status is how a stage moves from active to done or fail.
    """
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


def critique(bp: Any, payload: dict) -> dict:
    """Everything that can be known about a Blueprint before FreeCAD runs.

    Three checks, all arithmetic over the model's own expressions, all in about
    a millisecond against the three seconds a build costs:

    ``static``
        implicit — the Blueprint only exists here because ``freeze()`` accepted
        it, which is what rejects a bare number where an expression belongs.
    ``preconditions``
        every guard the model authored evaluates greater than zero. A violated
        guard means the closed form the part will be graded against is not valid
        for these values, so nothing built from it can verify.
    ``volume``
        the authored closed form against the profile builder's exact area times
        the extrusion length. Decidable only for a single-extrusion tree — where
        booleans between separately-sketched features can overlap, the analytic
        answer would be a guess and this reports ``unknown`` rather than
        pretending otherwise.

    These are the two failure classes that dominate live failures (see
    ``orion/reward.py``: the SFT corpus contains only verified records, so the
    model has never seen a bad dimension choice and its consequence). Reusing
    ``reward.analytic_volume`` rather than reimplementing it is deliberate: the
    critique a user reads is then the same function that scores an RL rollout,
    and the two cannot drift into disagreeing about the same part.

    Advisory, not a veto. ``design()`` still builds a Blueprint that fails here,
    because geometry a user can look at beats nothing even when it is refused —
    but the failure is named before the container starts rather than after.
    """
    from orion import reward

    checks: list[dict] = []
    blocking: list[str] = []

    checks.append(
        {
            "id": "static",
            "label": "Every dimension is an expression over a named variable",
            "status": "pass",
            "detail": f"{len(bp.variables)} variables, {len(bp.assertions)} assertions",
        }
    )

    try:
        rows = bp.resolve_assertions()
    except Exception as exc:  # noqa: BLE001 — an unresolvable Blueprint is a finding
        checks.append(
            {
                "id": "resolve",
                "label": "The Blueprint resolves to concrete numbers",
                "status": "fail",
                "detail": str(exc)[:200],
            }
        )
        return {
            "ok": False,
            "checks": checks,
            "blocking": ["resolve"],
            "advisories": [],
        }

    guards = [a for a in rows if a.get("kind") == "precondition"]
    failed = [
        a
        for a in guards
        if not (a.get("target_value") is not None and a["target_value"] > 0)
    ]
    if guards:
        checks.append(
            {
                "id": "preconditions",
                "label": "Every guard the model authored holds",
                "status": "fail" if failed else "pass",
                "detail": (
                    f"{len(failed)} of {len(guards)} violated: "
                    + ", ".join(str(a.get("id")) for a in failed)
                    if failed
                    else f"all {len(guards)} satisfied"
                ),
            }
        )
        if failed:
            blocking.append("preconditions")

    predicted = next(
        (a.get("target_value") for a in rows if a.get("kind") == "body_volume"), None
    )
    try:
        exact = reward.analytic_volume(bp)
    except Exception:  # noqa: BLE001 — undecidable is not a failure
        exact = None

    if predicted is not None and exact is not None:
        err = abs(predicted - exact) / max(abs(exact), 1e-12)
        agrees = err <= 1e-6
        checks.append(
            {
                "id": "volume",
                "label": "The predicted volume matches the profile it was derived from",
                "status": "pass" if agrees else "fail",
                "detail": f"closed form {predicted:.4f} mm^3 against "
                f"{exact:.4f} mm^3 from the sketch area"
                + ("" if agrees else f" — off by {err:.2%}"),
            }
        )
        if not agrees:
            blocking.append("volume")
    else:
        checks.append(
            {
                "id": "volume",
                "label": "The predicted volume matches the profile it was derived from",
                "status": "unknown",
                "detail": "not decidable without the kernel — this feature tree "
                "is not a single extrusion",
            }
        )

    try:
        from orion.checker import advisories

        notes = list(
            advisories(payload.get("variables") or {}, payload.get("template") or {})
        )
    except Exception:  # noqa: BLE001 — an advisory must never block a design
        notes = []

    return {
        "ok": not blocking,
        "checks": checks,
        "blocking": blocking,
        "advisories": notes,
    }


@dataclass
class Proposal:
    """A Blueprint the model has committed to, frozen, before any geometry.

    The point of the type is the hash. ``freeze()`` runs the static check and
    then sha256s every number the model authored, so a proposal names exactly
    one design and cannot be edited without becoming a different one. That is
    what an approval will bind to, and what lets ``build`` prove it is building
    the thing that was proposed rather than something that drifted in between.

    ``failure`` classifies a proposal that did not come off, in the vocabulary
    ``orion.repair_loop`` already switches on, so the caller can decide whether
    to repair (``parse``, ``freeze``) or stop (``model``, ``questions``).
    """

    ok: bool = False
    #: "" when ok, else one of: questions | model | parse | freeze
    failure: str = ""
    error: str = ""
    #: What the request would have to say before it can be designed at all.
    questions: list = field(default_factory=list)

    payload: dict = field(default_factory=dict)
    blueprint_hash: str = ""
    part_class: str = ""
    variables: dict = field(default_factory=dict)
    features: list = field(default_factory=list)
    design_plan: dict = field(default_factory=dict)
    assertions: list = field(default_factory=list)

    thinking: str = ""
    #: The raw completion, kept because a repair turn has to show the model its
    #: own failed attempt as its own.
    completion: str = ""
    model: str = ""
    volume_claim: dict = field(default_factory=dict)
    critique: dict = field(default_factory=dict)
    #: The deterministic engineering review of the resolved geometry — holes
    #: that clash, dimensions that cannot build, dressups too big for the face
    #: they land on. Distinct from ``critique``, which grades the model against
    #: its own contract; this grades the part against mechanics.
    mechanical: dict = field(default_factory=dict)

    route: dict = field(default_factory=dict)
    reasoning: Optional[dict] = None
    citations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    attempt: int = 1
    #: The two-message base this draw started from. Repair turns are rebuilt
    #: from it rather than appended to a growing history — see ``_repair_turn``.
    base_messages: list = field(default_factory=list)
    #: The reasoning chain, when one ran. Held as the object so the caller can
    #: still ask it to explain itself.
    chain: Any = None
    #: The user's own words. Carried because provenance is a claim about *this*
    #: request — "did they say 120?" is unanswerable once only the Blueprint is
    #: left — and a repair turn has to classify against the same text the first
    #: draw did, or a repaired part would grade its dimensions differently from
    #: the one it replaced.
    request: str = ""

    def to_dict(self) -> dict:
        """What a client is shown before anything is built or approved."""
        return {
            "blueprint_hash": self.blueprint_hash,
            "part_class": self.part_class,
            "variables": self.variables,
            "features": self.features,
            "design_plan": self.design_plan,
            "assertions": self.assertions,
            "critique": self.critique,
            "mechanical": self.mechanical,
            "attempt": self.attempt,
        }


def _carry_forward(history: Optional[list[dict]], message: str) -> str:
    """The whole request, when the last turn was a question.

    Walks back over the trailing user turns, stopping at the first assistant
    turn that was not a question — anything before that belongs to a request
    that has already been answered. The joined text is what the extraction
    reads, so "4 mm" is understood as the thickness of the bracket two turns up.

    An assistant turn is a question when it contains one. Every question this
    system emits comes from ``interview.question_for`` and ends in "?", so the
    test is precise in the direction that matters: a normal answer stops the
    walk, and a request is never silently merged into an unrelated one.
    """
    from orion import interview

    carried: list[str] = []
    asked = ""
    for turn in reversed(history or []):
        role, content = turn.get("role"), (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            if "?" not in content:
                break
            # The most recent question is the one ``message`` answers. Kept so
            # the answer can be bound to its field; joining the turns without
            # it leaves a bare "6 mm" for the extraction to place by guesswork,
            # and it guesses "nowhere".
            if not carried and not asked:
                asked = content
            continue
        if role == "user":
            carried.append(content)
    message = interview.phrase_answer(asked, message)
    if not carried:
        return message
    return chr(10).join(list(reversed(carried)) + [message])


def _failed_bundle(proposal: Proposal) -> dict:
    """A proposal that never reached the kernel, in the shape of a build result.

    Lets the orchestration rank and report every outcome the same way, whether
    it died at the model, at the parser or at the geometry.

    ``failure`` is carried rather than flattened into ``error``. A proposal that
    died because the endpoint serving our weights is down is an *environment*
    failure, and scoring it beside a part whose geometry was wrong makes the
    system look worse than it is — the benchmark that reported 36% counted five
    unreachable-endpoint rows as capability failures. Nothing downstream could
    tell them apart, because this shape dropped the one field that says which.
    """
    return {
        "success": False,
        "model": proposal.model,
        "error": proposal.error,
        "failure": proposal.failure,
        "verification": {},
        "files": {},
        "blueprint": proposal.payload or None,
        "part_class": proposal.part_class,
        "variables": proposal.variables,
        "critique": proposal.critique,
        "mechanical": proposal.mechanical,
        "attempts": proposal.attempt,
        "raw_completion": (proposal.completion or "")[:4000] or None,
    }


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

    def _reader(self):
        """The first reachable provider, for reading a request. ``None`` if none.

        Deliberately not the design model. Extraction is a comprehension task
        any competent model does, and the fine-tune's job is authoring geometry;
        binding this to ``DESIGN_MODEL`` would mean an outage on our weights
        also cost the request its duty, when the fallback could have read it
        perfectly well.
        """
        for provider in _in_health_order(_providers()):
            try:
                client = self._client(provider)
            except Exception as exc:  # noqa: BLE001 — try the next one
                logger.warning(
                    "duty_reader_unavailable", provider=provider, error=str(exc)
                )
                continue
            if serving_fine_tune(provider):
                client.model = CONVERSATION_MODEL
            return client
        return None

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
            "serving_our_model": serving_fine_tune(primary),
            # The adapter that actually authors geometry, which is the one a
            # user is asking about. This reported ``cfg.llm.model`` — the value
            # the agent loop and the conversation use — so a correctly
            # configured deployment could show "orionflow-base" on the
            # diagnostics panel while every part was being designed by
            # ``ORION_DESIGN_MODEL``. Health that names different weights than
            # produced the result is worse than no health at all, because it
            # sends you debugging the fine-tune instead of the config.
            "model": DESIGN_MODEL,
            "conversation_model": CONVERSATION_MODEL,
            #: What the shared config carries, for when the two disagree.
            "configured_model": cfg.llm.model,
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

        for provider in _in_health_order(_providers()):
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
            # ``model`` names an adapter on OUR endpoint — "orionflow" and
            # "orionflow-base" are the LoRA and its base, served side by side.
            # It is a vLLM extension: ``LLMClient.chat`` does not declare it and
            # a vendor adapter does not accept it, so passing it to a fallback
            # raised TypeError out of ``chat_stream`` and took the whole turn
            # with it. Every design draw and every conversation turn sets it, so
            # with the GPU down the model path and the assistant panel both
            # crashed on the fallback that exists to keep them working. Sending
            # our adapter's name to somebody else's API would be meaningless
            # even where it did not crash: that endpoint serves one model.
            kw = {"model": model} if model and serving_fine_tune(provider) else {}
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
                _mark_up(provider)
                return resp, label
            _mark_down(provider, resp.content)
            logger.warning(
                "studio_provider_failed", provider=provider, detail=resp.content[:200]
            )

        return None, ""

    # ------------------------------------------------------------------ #
    # propose → build
    #
    # These were one method, and the seam mattered more than it looked.
    # Everything before the kernel — routing the request, deriving dimensions
    # from a duty, drawing a Blueprint, freezing it, and settling what
    # arithmetic alone can settle — is cheap, reversible, and the part worth
    # showing to a person. Everything after it costs a FreeCAD container and
    # produces a solid. Fused, there was no moment at which a design existed but
    # had not yet been built, and therefore nowhere to put an approval, a
    # revision, or a critique that could have saved the build.
    # ------------------------------------------------------------------ #
    def propose(self, prompt: str, on_event: EventSink = None) -> Proposal:
        """Prompt → a frozen Blueprint and its pre-build critique. No geometry.

        Runs the deterministic stages first — see ``app/services/design_router``
        for why a stated load, and only a stated load, diverts to the reasoning
        chain — then takes one draw from the model and freezes what comes back.
        """
        from app.services import design_router
        from orion.pack_sft import SYSTEM_PROMPT
        from orion_agent.harness.llm.base import LLMMessage

        # A request that states a duty is not a description of a part, it is a
        # question about one, and the answer is arithmetic over catalogues and
        # standards rather than anything a model should be sampling.
        # The deterministic path first, wherever it applies.
        #
        # Measured on four industrial requests and a terse plate: with Python
        # writing the Blueprint, five of five froze, built, verified and were
        # faithful to what was asked. With a model writing it, one of five —
        # the base model failed the static check on every complex part, and the
        # LoRA returned l_bracket_plus_counterbore_set_vent_slot for a request
        # that had already stated every dimension. The prior that adds features
        # is in the weights and no prompt reaches it.
        #
        # The LoRA still answers everything this has no builder for, which is
        # most of the vocabulary. It is no longer the default for the part
        # classes we can construct.
        det = self._deterministic(prompt, on_event)
        if det is not None:
            return det

        # Past this line the Blueprint is authored by a model, and only our own
        # weights were ever trained to author one. When none is reachable, say
        # so now: a general model spends two sampling rounds arriving at "no
        # Blueprint JSON in completion" — measured 22-49s for a spur gear — and
        # a stated limit is a better answer than a slow parse error, especially
        # since the four compiled families above are unaffected by the outage.
        if not any(serving_fine_tune(p) and not _is_down(p) for p in _providers()):
            from orion import blueprint_gen, interview

            buildable = ", ".join(
                interview.FAMILIES[f].label if f in interview.FAMILIES else f
                for f in sorted(blueprint_gen.BUILDERS)
            )
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "fail",
                "no builder for this part, and the design model is offline",
            )
            return Proposal(
                failure="model",
                error=(
                    "This part has no deterministic builder, and the fine-tuned "
                    "model that authors everything else is not currently being "
                    f"served. I can still build these exactly: {buildable}."
                ),
                route=design_router.Route(
                    design_router.DIRECT,
                    "no builder for this family and no fine-tuned model to author one",
                ).to_dict(),
            )

        # A client for the duty read, not for the routing decision — see
        # ``design_router.decide``. Reached only here, past the deterministic
        # builders, so a request a builder handles never pays for it. A dead
        # provider costs the second reading and nothing else: the patterns
        # still run and the branch rule is unchanged.
        route = design_router.resolve(prompt, client=self._reader())
        model_prompt = prompt
        chain = route.chain
        if route.duty_notes:
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "done",
                "duty read",
                list(route.duty_notes),
            )

        if route.to_branch:
            _emit_step(
                on_event, "understand", "Understanding the request", "active", route.why
            )
            if chain is not None and not chain.complete:
                # The chain stopped because the request did not say enough. Its
                # questions are the useful answer — inventing the missing number
                # is exactly the failure the chain exists to prevent — so the
                # turn ends here rather than handing the model a gap to fill.
                _emit_step(
                    on_event,
                    "understand",
                    "Understanding the request",
                    "fail",
                    f"stopped at {chain.stopped_at}",
                    chain.asks(),
                )
                return Proposal(
                    failure="questions",
                    error="; ".join(chain.asks())
                    or f"the request could not be specified "
                    f"(stopped at {chain.stopped_at})",
                    questions=chain.asks(),
                    route=route.to_dict(),
                    reasoning=chain.to_dict(),
                    chain=chain,
                )
            if chain is not None:
                # Every dimension now comes from a standard or a calculation, and
                # the model's only remaining job is to render it as a coherent
                # Blueprint. The branch states those dimensions in the register
                # the model was fine-tuned on and withholds the reasoning — the
                # derivation is for the user, and feeding it back invites the
                # model to re-litigate settled arithmetic.
                model_prompt = route.design_prompt
                _emit_step(
                    on_event,
                    "specify",
                    "Specifying the design",
                    "done",
                    f"{len(chain.variables)} dimensions derived",
                    [f"{k} = {v:g}" for k, v in sorted(chain.variables.items())]
                    + list(chain.citations),
                )

        # Turn 1 is the ONLY turn that must match training byte for byte, so it
        # is built from these two messages and nothing else, every time. Repair
        # turns are rebuilt from this same pair plus the failed attempt and its
        # diagnosis — never by appending to a growing history, which would put a
        # second user turn in front of the model on attempt 3 and stop looking
        # like the repair records at all.
        base = [LLMMessage.system(SYSTEM_PROMPT), LLMMessage.user(model_prompt)]
        return self._draw(base, base, route, chain, 1, on_event, request=prompt)

    def _deterministic(
        self, prompt: str, on_event: EventSink = None
    ) -> Optional[Proposal]:
        """Interview, then compile in Python. ``None`` to fall through.

        Three outcomes, and none of them is a model writing geometry:

        * a frozen Blueprint, built from a schema and arithmetic;
        * a question, when the request left a required field open — which is
          the honest answer to "four slots near each corner", a size with no
          position;
        * a refusal naming the number that is wrong, when the geometry cannot
          exist.

        A refusal is returned rather than handed to the LoRA. Falling back would
        answer "your counterbores break into the base plate" with a part that
        quietly did something else, which is the failure mode this replaces.
        """
        from app.services import design_router, mechanical_plan
        from orion import blueprint_gen, interview
        from orion.blueprint import Blueprint, BlueprintError

        # The base adapter reads the request. ``_client`` is keyed by *provider*
        # — the model is a separate field on the client, and passing a model id
        # where a provider belongs fails as "unknown LLM provider", which reads
        # like a misconfigured deployment rather than a wrong argument.
        #
        # Every provider is tried, and the fallback is reached when the *call*
        # fails rather than only when the client cannot be constructed.
        # Constructing a client against a dead endpoint succeeds — nothing
        # connects until the first request — so the old loop bound to the
        # primary, took a transport error from it, and returned None. With the
        # GPU down that skipped this whole path for every request and handed
        # each one to a general model asked to author Blueprint JSON, which is
        # the 1-of-5 outcome this module was written to replace. The
        # architecture was intact and unreachable.
        iv = None
        read_by = ""
        read_error = ""
        for provider in _in_health_order(_providers()):
            try:
                client = self._client(provider)
                if serving_fine_tune(provider):
                    client.model = CONVERSATION_MODEL
            except Exception as exc:  # noqa: BLE001 - try the fallback
                logger.warning(
                    "interview_provider_failed", provider=provider, error=str(exc)
                )
                continue

            try:
                candidate = interview.read_request(
                    client, prompt, max_tokens=interview.READ_TOKENS
                )
            except Exception as exc:  # noqa: BLE001 - a dead endpoint is not a refusal
                logger.warning("interview_failed", provider=provider, error=str(exc))
                _mark_down(provider, str(exc))
                continue

            if candidate.transport_error:
                read_error = candidate.transport_error
                _mark_down(provider, candidate.transport_error)
                continue

            _mark_up(provider)
            iv, read_by = candidate, provider
            break

        if iv is None:
            # No provider could read the request. That is an *environment*
            # failure and it must not fall through: past this point the caller
            # answers "this part has no deterministic builder", which is a
            # claim about our capability, and it is false for the four families
            # we compile. A rate-limited endpoint made
            # "Rectangular plate 100 x 60 x 5 mm" — the simplest prompt in the
            # bench, and a compiled family — report that it could not be built
            # deterministically. The request was never read; nothing at all is
            # known about which family it is.
            buildable = ", ".join(
                interview.FAMILIES[f].label if f in interview.FAMILIES else f
                for f in sorted(blueprint_gen.BUILDERS)
            )
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "fail",
                "could not reach a model to read the request",
                [read_error] if read_error else [],
            )
            return Proposal(
                failure="model",
                error=(
                    "I could not reach a model to read your request, so I do "
                    "not yet know what to build. This is an outage on our side, "
                    f"not a limit of the design: {read_error or 'endpoint unavailable'}. "
                    f"These build exactly once it is back: {buildable}."
                ),
                route=design_router.Route(
                    design_router.DIRECT,
                    "the request could not be read; no family was determined",
                ).to_dict(),
            )

        if iv.family not in blueprint_gen.BUILDERS:
            return None

        _emit_step(
            on_event,
            "understand",
            "Understanding the request",
            "done",
            f"{interview.FAMILIES[iv.family].label}, "
            f"{len(iv.slots)} dimensions read",
            [f"{k} = {v}" for k, v in sorted(iv.slots.items())],
        )

        if not iv.complete:
            # Both kinds of gap: slots the schema requires and nobody filled,
            # and dimensions the request stated that no slot took. Asking only
            # the first let "Tube 40 mm OD, 32 mm ID, 60 mm long" build as a
            # solid bar and grade VERIFIED.
            asks = interview.open_questions(iv)
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "fail",
                "the request does not say enough yet",
                asks,
            )
            return Proposal(
                failure="questions",
                error="; ".join(asks),
                questions=asks,
                reasoning=iv.to_dict(),
            )

        try:
            payload = interview.build(iv)
        except blueprint_gen.GeneratorError as exc:
            _emit_step(
                on_event,
                "specify",
                "Specifying the design",
                "fail",
                _short(str(exc)),
                [str(exc)],
            )
            return Proposal(
                failure="questions",
                error=str(exc),
                questions=[str(exc)],
                reasoning=iv.to_dict(),
            )

        try:
            bp = Blueprint.from_dict(payload).freeze()
        except (BlueprintError, ValueError, KeyError, TypeError) as exc:
            # The generator wrote something the static check rejects, which is a
            # bug here rather than anything the user did. Fall through to the
            # model rather than dead-end a request we could still serve.
            logger.warning(
                "generator_blueprint_rejected", error=str(exc), family=iv.family
            )
            return None

        _emit_step(
            on_event,
            "specify",
            "Specifying the design",
            "done",
            f"{len(bp.variables)} variables, "
            f"{len(payload['template']['features'])} features "
            f"— compiled, not generated",
            [f"{k} = {v:g}" for k, v in sorted(bp.variables.items())],
        )

        return Proposal(
            ok=True,
            payload=payload,
            blueprint_hash=bp.blueprint_hash,
            part_class=bp.part_class,
            variables=dict(bp.variables),
            features=list(payload["template"]["features"]),
            design_plan=payload.get("design_plan", {}),
            assertions=list(bp.assertions),
            reasoning=iv.to_dict(),
            # Named, because this path produced no model-authored geometry and
            # the badge hides itself when the label is empty. A compiled part
            # was therefore the one result in the studio with no provenance at
            # all — indistinguishable, to anyone watching, from our fine-tune
            # having produced it. The label states what actually happened: the
            # geometry was compiled in Python, and this provider only read the
            # request into slots.
            model=f"compiled:{read_by}",
            # Compiled Blueprints are graded by the same two reviews as authored
            # ones. Not because the generator is expected to fail them — its
            # volume is derived alongside the geometry rather than predicted
            # about it — but because a proposal that carries no checks renders
            # as a part nobody examined, and "compiled deterministically" is a
            # claim about provenance, not evidence that the numbers work. A
            # violated guard is now named here rather than after a container has
            # started, exactly as on the model path.
            critique=critique(bp, payload),
            mechanical=mechanical_plan.review_blueprint(bp),
            route=design_router.Route(
                design_router.DIRECT, "compiled deterministically from the interview"
            ).to_dict(),
            request=prompt,
        )

    def repropose(
        self, previous: Proposal, diagnosis: str, on_event: EventSink = None
    ) -> Proposal:
        """Another draw, given exactly why the last one failed.

        A failed attempt is never resampled blind: the same prompt draws the
        same reasoning, so blind resampling cannot fix a wrong derivation. The
        diagnosis is derived from measured evidence — which assertion missed, by
        how much, and which feature's own volume accounts for the gap.
        """
        messages = _repair_turn(previous.base_messages, previous.completion, diagnosis)
        return self._draw(
            messages,
            previous.base_messages,
            previous.route,
            previous.chain,
            previous.attempt + 1,
            on_event,
            request=previous.request,
        )

    def redesign(
        self,
        prompt: str,
        previous: dict,
        instruction: str,
        attempt: int = 1,
        on_event: EventSink = None,
    ) -> Proposal:
        """Redraw a stored design because a person asked for a change.

        Reconstructed from the persisted Blueprint rather than from a live
        conversation, because a revision can be asked for days after the
        proposal and nothing in memory survives that. The shape is the same as a
        repair turn — original ask, the design as the model's own answer, then
        what is wrong with it — so the model sees its previous output as its own
        and edits rather than starting over. What differs is the last turn: a
        repair carries a diagnosis the verifier derived, this carries a person's
        words, and the two must not be conflated in the record.
        """
        import json

        from orion.pack_sft import SYSTEM_PROMPT
        from orion_agent.harness.llm.base import LLMMessage

        base = [LLMMessage.system(SYSTEM_PROMPT), LLMMessage.user(prompt)]
        messages = base + [
            LLMMessage.assistant(json.dumps(previous)),
            LLMMessage.user(
                f"Change that part as follows.\n\n{instruction}\n\n"
                "Keep everything the change does not touch. Re-derive the "
                "volume if the change affects it, then emit the corrected "
                "Blueprint as a single JSON object."
            ),
        ]
        from app.services import design_router

        route = design_router.Route(
            design_router.DIRECT, "a revision of an existing design"
        )
        return self._draw(messages, base, route, None, attempt, on_event)

    def _draw(
        self,
        messages: list,
        base_messages: list,
        route: Any,
        chain: Any,
        attempt: int,
        on_event: EventSink,
        request: str = "",
    ) -> Proposal:
        """One model draw, parsed, frozen and critiqued. The half that costs tokens."""
        from app.services import blueprint_service, design_narrative, mechanical_plan
        from orion import calc
        from orion.blueprint import Blueprint, BlueprintError

        route_dict = route.to_dict() if hasattr(route, "to_dict") else dict(route or {})

        def failed(
            kind: str, error: str, completion: str = "", model: str = ""
        ) -> Proposal:
            return Proposal(
                failure=kind,
                error=error,
                completion=completion,
                model=model,
                attempt=attempt,
                route=route_dict,
                chain=chain,
                base_messages=base_messages,
                request=request,
            )

        _emit_step(
            on_event,
            "understand",
            "Understanding the request",
            "active",
            f"repair attempt {attempt}" if attempt > 1 else "",
        )
        if on_event:
            on_event("phase", {"phase": "reasoning"})

        # channel=None: emit no raw tokens. See _complete for why.
        resp, label = self._complete(
            messages, on_event, channel=None, max_tokens=4096, model=DESIGN_MODEL
        )
        if resp is None:
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "fail",
                "no model is reachable",
            )
            return failed(
                "model",
                "no model is reachable — the inference endpoint is down and "
                "the fallback also failed",
            )

        completion = resp.content

        try:
            _, payload = blueprint_service.parse_completion(completion)
        except blueprint_service.BlueprintBuildError as exc:
            # The model answered, but not with a Blueprint. That is a model
            # failure and must read as one — not as a kernel error.
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "fail",
                "the model did not return a Blueprint",
            )
            return failed("parse", str(exc), completion, label)

        # Stamped before the freeze, deliberately. The ledger says where each
        # of these numbers came from, and a record added after the part was
        # measured would prove nothing — the same reason the assertions are
        # frozen. Inside the hash it is a commitment; outside it is a caption.
        payload = _with_provenance(payload, request, chain)

        # Frozen here rather than at build time, which is the whole point of
        # the split: the hash covers every number the model authored, so from
        # this line on the design has an identity that a build can be checked
        # against. A static rejection is the model failing its own contract, and
        # is now named before a container is started rather than after.
        try:
            bp = Blueprint.from_dict(payload).freeze()
        except (BlueprintError, KeyError, TypeError, ValueError) as exc:
            _emit_step(
                on_event,
                "understand",
                "Understanding the request",
                "fail",
                _short(str(exc)),
            )
            return failed("freeze", f"blueprint rejected: {exc}", completion, label)

        variables = dict(bp.variables)
        features = [
            f
            for f in (bp.template.get("features") or [])
            if f.get("type") not in ("Body", "Sketch")
        ]

        _emit_step(
            on_event,
            "understand",
            "Understanding the request",
            "done",
            design_narrative._readable_class(bp.part_class),
        )
        _emit_step(
            on_event,
            "dimensions",
            "Solving dimensions",
            "done",
            f"{len(variables)} parameters",
            [f"{k} = {v}" for k, v in variables.items()],
        )

        thinking = resp.thinking or ""
        proposal = Proposal(
            ok=True,
            payload=payload,
            blueprint_hash=bp.blueprint_hash,
            part_class=bp.part_class,
            variables=variables,
            features=features,
            design_plan=dict(bp.design_plan or {}),
            assertions=list(bp.assertions or []),
            thinking=thinking,
            completion=completion,
            model=label,
            # The model states a number at the end of its derivation and never
            # evaluates it — measured across the held-out set, that number
            # disagrees with the model's OWN expression in every single case,
            # including parts that go on to verify. The expression is the
            # contract; the prose is decoration. Recomputed here so the raw
            # derivation is never shown to a user as if it were arithmetic.
            volume_claim=calc.check_stated_volume(payload, thinking),
            critique=critique(bp, payload),
            mechanical=mechanical_plan.review_blueprint(bp),
            route=route_dict,
            reasoning=chain.to_dict() if chain is not None else None,
            citations=list(chain.citations) if chain is not None else [],
            warnings=list(chain.warnings) if chain is not None else [],
            attempt=attempt,
            base_messages=base_messages,
            chain=chain,
            request=request,
        )

        if on_event:
            on_event("proposal", proposal.to_dict())
        return proposal

    def build(
        self, proposal: Proposal, on_event: EventSink = None, prompt: str = ""
    ) -> dict:
        """A frozen Blueprint → geometry, measured and graded. No model call.

        Refuses a payload that no longer hashes to the proposal's own hash.
        Nothing between ``propose`` and here mutates a payload today, so that
        check can only fire on a bug — but it is precisely the check an approval
        gate is made of, and it is worth having in place before anything is
        allowed to sit in the gap.
        """
        from app.services import blueprint_service

        if not proposal.ok:
            return _failed_bundle(proposal)

        _emit_step(
            on_event,
            "build",
            "Building the model",
            "active",
            f"{len(proposal.features)} features",
            [f.get("rationale") or f.get("id", "") for f in proposal.features],
        )
        if on_event:
            on_event("phase", {"phase": "building"})

        bundle = blueprint_service.build_from_payload(proposal.payload)

        built = (bundle.get("blueprint") or {}).get("blueprint_hash", "")
        if built and proposal.blueprint_hash and built != proposal.blueprint_hash:
            bundle["success"] = False
            bundle["error"] = (
                "the Blueprint changed between proposal and build "
                f"({proposal.blueprint_hash[:10]} → {built[:10]})"
            )

        bundle["model"] = proposal.model
        bundle["thinking"] = proposal.thinking
        bundle["prompt"] = prompt
        bundle["attempts"] = proposal.attempt
        bundle["volume_claim"] = proposal.volume_claim
        bundle["critique"] = proposal.critique
        bundle["mechanical"] = proposal.mechanical
        return bundle

    # ------------------------------------------------------------------ #
    def design(self, prompt: str, on_event: EventSink = None,
               history: Optional[list[dict]] = None) -> dict:
        """Prompt → Blueprint → geometry → verdict.

        Orchestration only: ``propose`` draws and freezes, ``build`` runs the
        kernel, and this decides how many times to try and which result to keep.
        The repair budget, the keep-the-best-attempt rule and the event stream
        are unchanged from when this was one method.

        Emits ``step`` events as each stage genuinely completes. They are
        derived from real state — the parsed part class, the actual feature
        list, the checks that ran — never from a timer, so a stalled stage looks
        stalled instead of animating cheerfully towards a result that will not
        arrive.
        """
        from orion import repair_loop

        # An answer to a question is not a new request. The interview asks
        # "How thick is the base plate?", the user types "4 mm", and until now
        # that answer arrived on its own — a fresh extraction against three
        # characters, with the part it described already forgotten. Carried
        # forward here rather than inside the interview so every route below
        # sees one complete request.
        prompt = _carry_forward(history, prompt)
        proposal = self.propose(prompt, on_event)
        if proposal.failure == "questions":
            return {
                "success": False,
                "model": "",
                "error": proposal.error,
                "needs": proposal.questions,
                "reasoning": proposal.reasoning,
                "verification": {},
                "files": {},
            }

        best: dict = {}
        best_proposal = proposal
        bundle: dict = {}

        while True:
            bundle = (
                self.build(proposal, on_event, prompt=prompt)
                if proposal.ok
                else _failed_bundle(proposal)
            )

            # Keep the best result seen, not the last one. A later attempt that
            # fails to parse must not throw away an earlier part that built —
            # geometry the user can look at beats nothing, even unverified.
            if _rank(bundle) > _rank(best):
                best, best_proposal = bundle, proposal

            if _rank(bundle) >= _UNSOURCED or proposal.attempt >= DESIGN_ATTEMPTS:
                break
            if proposal.failure == "model":
                # Nothing to repair — the endpoint is down, and asking it again
                # with a diagnosis will reach the same dead socket. An endpoint
                # that dies on the repair turn must not cost the user a part
                # that already built on the first one, which is what keeping
                # ``best`` above is for.
                break

            if not proposal.base_messages:
                # A compiled Blueprint has no conversation to repair from, and
                # must not acquire one. ``_deterministic`` authors no messages,
                # so the repair turn was built from an empty base and reached
                # the model as two turns — an empty assistant reply and a
                # diagnosis — with no system prompt and no original request:
                # the model asked to author a Blueprint out of nothing. Worse
                # than the wasted round trip, a reply that happened to parse and
                # verify would outrank the compiled attempt and silently replace
                # deterministic geometry with a model's guess, which is the one
                # substitution this architecture exists to prevent.
                #
                # A compiled part that fails is a generator or kernel defect.
                # Resampling cannot fix it, and the failure belongs in the
                # report where someone will see it.
                break

            blocking = (proposal.mechanical or {}).get("blocking", 0)
            if proposal.ok and blocking and bundle.get("error"):
                # The kernel failed *and* the deterministic review had already
                # said why. Lead with the mechanical finding: it names the
                # coordinates that clash, which a stderr tail from OCC never
                # does, and the model repairs a derivation it can see is wrong
                # far more reliably than one it is merely told is wrong.
                from app.services import mechanical_plan

                diagnosis = mechanical_plan.as_diagnosis(proposal.mechanical)
                _emit_step(
                    on_event,
                    "build",
                    "Building the model",
                    "active",
                    f"{blocking} geometry problem"
                    f"{'s' if blocking != 1 else ''} — repairing",
                )
                if on_event:
                    on_event(
                        "repair",
                        {
                            "attempt": proposal.attempt,
                            "error": "mechanical",
                            "diagnosis": diagnosis,
                        },
                    )
            elif proposal.failure in ("parse", "freeze"):
                # Caught before the kernel, so this repair round costs a model
                # call and nothing else.
                diagnosis = repair_loop.diagnose(
                    proposal.payload or None, f"{proposal.failure}: {proposal.error}"
                )
                _emit_step(
                    on_event,
                    "understand",
                    "Understanding the request",
                    "active",
                    "no Blueprint returned — asking again with the reason",
                )
            else:
                error, verdict = _classify_failure(bundle)
                diagnosis = repair_loop.diagnose(
                    proposal.payload,
                    error,
                    verdict=verdict,
                    measured=bundle.get("measured"),
                )
                _emit_step(
                    on_event,
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
                        {
                            "attempt": proposal.attempt,
                            "error": error,
                            "diagnosis": diagnosis,
                        },
                    )

            proposal = self.repropose(proposal, diagnosis, on_event)

        attempts = proposal.attempt
        proposal = best_proposal
        bundle = best or bundle
        # How many attempts the turn actually cost, not how many the surviving
        # bundle happened to be produced on. When every attempt fails at the
        # same rank the first one is kept, and reporting its ``attempts`` of 1
        # hides the repair round entirely from anything counting them.
        if bundle:
            bundle["attempts"] = attempts
        return self._report(bundle, proposal, on_event, prompt)

    # ------------------------------------------------------------------ #
    def _report(
        self, bundle: dict, proposal: Proposal, on_event: EventSink, prompt: str
    ) -> dict:
        """Announce the outcome and attach everything derived from it.

        Separate from ``build`` because a build is one attempt and this is the
        turn's verdict: it runs once, over whichever attempt was kept.
        """
        from app.services import design_narrative

        if not bundle.get("success"):
            _emit_step(
                on_event,
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

        _emit_step(
            on_event,
            "build",
            "Building the model",
            "done",
            f"{len(proposal.features)} features",
        )
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
        # Keyed on whether anything actually failed, not on the verdict being
        # exactly "verified". An UNSOURCED part passed every geometry check it
        # ran; marking the stage red would say the build broke, when what
        # happened is that some of its dimensions are unaccounted for.
        _emit_step(
            on_event,
            "verify",
            "Running verification",
            "fail" if report.get("failed") else "done",
            f"{len(checks)} checks",
            [c.get("label", "") for c in checks],
        )
        if on_event:
            on_event("verification", report)

        # How the request was routed, and — when the chain ran — the derivation
        # behind every dimension. This is the half of the answer the model did
        # not produce, and the half an engineer can check: each number traceable
        # to the stage, standard or calculation that decided it.
        bundle["route"] = proposal.route
        if proposal.chain is not None:
            bundle["reasoning"] = proposal.reasoning
            bundle["citations"] = proposal.citations
            if proposal.warnings:
                bundle.setdefault("warnings", []).extend(proposal.warnings)
            if on_event:
                on_event(
                    "reasoning",
                    {
                        "explain": proposal.chain.explain(),
                        "citations": proposal.citations,
                        "warnings": proposal.warnings,
                        "part_class": proposal.chain.part_class,
                        "variables": dict(proposal.chain.variables),
                    },
                )

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
        lens: Optional[str] = None,
        request_id: str = "",
        on_event: EventSink = None,
    ) -> dict:
        """Answer a question about the current part, grounded in its report."""
        from orion_agent.harness.llm.base import LLMMessage

        # Tools first: the system prompt has to know whether the geometry is
        # actually reachable this turn before it tells the model to go and look.
        registry = _part_registry(request_id, part)
        can_inspect = registry is not None
        if registry is None:
            registry = _knowledge_registry()

        messages = [
            LLMMessage.system(
                lens_system(lens, has_part=bool(part), can_inspect=can_inspect)
            )
        ]

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

        # Two tool surfaces, chosen above. Knowledge alone — ISO/DIN lookups,
        # the NASA requirement graph, materials, sheet-metal DFM — when there is
        # no build to point at; knowledge plus this build's own topology,
        # feature parameters and measurements when there is. Quoting a real
        # clause beats paraphrasing one from memory, and reading a real face
        # beats inferring one from a summary. Both are checkable.
        schemas = registry.schemas() if registry else None

        used: list[str] = []
        rounds = INSPECTION_TOOL_ROUNDS if can_inspect else KNOWLEDGE_TOOL_ROUNDS
        for _round in range(rounds):
            resp, label = self._complete(
                messages,
                on_event,
                "answer",
                max_tokens=ANSWER_TOKENS,
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
                messages,
                on_event,
                "answer",
                max_tokens=ANSWER_TOKENS,
                model=CONVERSATION_MODEL,
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
            # Two different failures, and they were reported as one. A reply
            # cut off mid-derivation arrives with no content at all, which is
            # indistinguishable here from a Blueprint that was stripped — so a
            # truncated answer told the user to rephrase a question that was
            # never the problem. Name the one that actually happened.
            if resp.finish_reason == "length":
                return {
                    "success": False,
                    "model": label,
                    "answer": "",
                    "error": "the model ran out of room before it answered — "
                    "raise ORION_ANSWER_TOKENS or ask something narrower",
                }
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
            # Whether the geometry was reachable at all this turn — distinct
            # from whether the model chose to look. Both matter to a reader
            # deciding how much weight a number in the answer carries.
            "inspected": can_inspect,
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

    # -- The rest of the engineering state the studio has in front of it.
    #
    # Everything above describes the part in the abstract. What follows is the
    # user's *situation*: what they are pointing at, how the part was built,
    # what they have done to it recently, and what went wrong last. Without
    # these the assistant answers about a part; with them it answers about the
    # part on this screen, which is the difference between a chatbot beside CAD
    # and a CAD system you can talk to.
    #
    # All of it is optional. A client that sends none of these keys gets
    # exactly the context it did before, so an older frontend still works.

    selection = part.get("selection") or {}
    if selection.get("face"):
        bits = [f"face {selection['face']}"]
        if selection.get("feature"):
            bits.append(f"authored by feature {selection['feature']}")
        if selection.get("surface"):
            bits.append(str(selection["surface"]).split("::")[-1])
        if selection.get("radius") is not None:
            bits.append(f"radius {selection['radius']} mm")
        if selection.get("area") is not None:
            bits.append(f"area {selection['area']} mm^2")
        lines.append("")
        lines.append(
            "The user has selected " + ", ".join(bits) + ". When they say "
            '"this", "that face" or "it", that is what they mean.'
        )
    elif selection.get("faces"):
        shown = list(selection["faces"])[:12]
        note = f" ({selection['note']})" if selection.get("note") else ""
        lines.append("")
        lines.append(
            f"The user has {len(selection['faces'])} faces selected{note}: "
            + ", ".join(str(f) for f in shown)
            + "."
        )

    tree = part.get("feature_tree")
    if tree:
        lines.append("")
        lines.append("Feature history, in build order:")
        for feat in list(tree)[:24]:
            status = feat.get("status") or "unknown"
            mark = "" if status == "success" else f"  [{status}]"
            label = f" - {feat.get('label')}" if feat.get("label") else ""
            lines.append(f"  {feat.get('id')}: {feat.get('type')}{label}{mark}")

    recent = part.get("recent_operations") or []
    if recent:
        lines.append("")
        lines.append(
            "Recent operations on this part, oldest first: "
            + " -> ".join(str(r) for r in recent)
        )

    if part.get("contract_broken"):
        lines.append("")
        lines.append(
            "This part has been hand-edited since it was designed, so the "
            "model's original assertions no longer describe this geometry. Do "
            "not present the verdict as a grade of the part as it now stands."
        )

    if part.get("last_error"):
        lines.append("")
        lines.append(
            f"The last thing that failed in this session: {part['last_error']}. "
            "If the user is following up on it, address that."
        )

    return "\n".join(lines)


_agent: Optional[StudioAgent] = None


def get_studio_agent() -> StudioAgent:
    global _agent
    if _agent is None:
        _agent = StudioAgent()
    return _agent
