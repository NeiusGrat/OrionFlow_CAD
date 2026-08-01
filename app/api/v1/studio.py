"""Studio endpoints — the fine-tuned model, streamed.

``POST /studio/chat`` is server-sent events rather than a single JSON reply for
one reason: the interesting part of this model is the derivation it writes
before any geometry exists, and a spinner that hides it for forty seconds
throws away the only evidence a user has that the system is reasoning rather
than guessing. Events are emitted as they happen — no simulated progress.

Event types, in the order they can appear::

    model        which model answered ("orionflow" or "fallback:<provider>")
    phase        reasoning | building
    thinking     a token of the derivation
    answer       a token of the reply (conversation turns)
    built        geometry exists: files, measured stats
    verification the verdict and every check that actually ran
    done         terminal; carries the full bundle
    error        terminal; nothing usable was produced
"""

import json
import queue
import threading
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logging_config import get_logger
from app.services.studio_persistence import StudioGate, studio_gate

logger = get_logger(__name__)
router = APIRouter(tags=["Studio"])

#: A build can legitimately take a couple of minutes; the reader must not give
#: up before the worker does. Only guards against a producer that dies without
#: posting a terminal event.
STREAM_TIMEOUT_S = 600


class StudioChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    #: The part currently open, if any — its Blueprint, stats and verification
    #: report. Sent by the client so a stateless worker can still talk about
    #: "this part".
    part: Optional[dict[str, Any]] = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    #: Force a route instead of inferring one: "design" | "explain".
    intent: Optional[str] = None
    #: What the assistant is being asked to look at — geometry, or one of the
    #: manufacturing lenses. Conversation only; see ``LENS_BRIEFS``.
    lens: Optional[str] = None


@router.get("/health")
def studio_health(authorization: Optional[str] = Header(None)):
    """Which model and which builder this instance would actually use.

    Deliberately reachable without a token so an uptime monitor can use it —
    but the inference endpoint is redacted for anonymous callers. It is the
    address of our own GPU host, and publishing it on an open route invites
    traffic that bypasses this API entirely. Signed-in callers still get it;
    the studio's diagnostics panel shows it.

    Resolves the caller from the header directly rather than through
    ``studio_gate``: a health check should not run a quota query.
    """
    from app.services.ofl_telemetry import user_id_from_auth_header
    from app.services.studio_agent import get_studio_agent

    report = get_studio_agent().health()
    if user_id_from_auth_header(authorization) is None:
        report.pop("endpoint", None)
    return report


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _feature_tree_for(bundle: dict) -> dict:
    """The build's feature history, or an empty tree if it cannot be assembled.

    Never allowed to fail the turn: the user has a part, and losing it because
    a history could not be derived from it would be a poor trade.
    """
    from app.services import feature_tree
    from app.services.studio_persistence import build_evidence

    try:
        return feature_tree.build(bundle.get("blueprint"), build_evidence(bundle))
    except Exception:  # noqa: BLE001
        logger.warning("studio_feature_tree_failed", exc_info=True)
        return feature_tree.empty()


async def _record_when_finished(
    produced: dict, prompt: str, user_id: Optional[Any]
) -> None:
    """Write the build record once the stream has closed.

    Reads the bundle at call time rather than taking it as an argument, because
    the task is registered while the worker is still running. A worker that died
    before producing anything leaves nothing to record, which is correct: there
    is no build to describe and nothing to charge for.
    """
    from app.services.studio_persistence import record_studio_build

    bundle = produced.get("bundle")
    if bundle:
        await record_studio_build(bundle, prompt, user_id)


@router.post("/chat")
def studio_chat(
    request: StudioChatRequest,
    background: BackgroundTasks,
    gate: StudioGate = Depends(studio_gate),
):
    """One studio turn: either design a part, or talk about the open one."""
    from app.services.studio_agent import get_studio_agent, _looks_like_a_question

    # Both roles call a model we pay for by the second, so neither is given
    # away unattributed: an unmetered anonymous route is a way to spend our own
    # inference budget without limit, and signing out would otherwise be a way
    # around the quota. Safe to require — the studio sits behind the frontend's
    # protected route and nothing else calls this endpoint.
    if not gate.known:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "sign in to design with OrionFlow",
                "reason": "authentication_required",
            },
        )

    agent = get_studio_agent()

    intent = request.intent
    if intent not in ("design", "explain"):
        # No part open means there is nothing to discuss yet, so even a
        # question becomes a design request.
        intent = (
            "explain"
            if request.part and _looks_like_a_question(request.message)
            else "design"
        )

    # Only designing costs anything — a build is an LLM call plus a FreeCAD
    # container. Talking about a part the user already has is free, and metering
    # it would make the honest thing (asking whether the part is right) the
    # expensive one. Refused before the stream opens, so the client gets a
    # status code it can act on rather than an error event inside a 200.
    if intent == "design" and not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": gate.message or "monthly generation limit reached",
                "reason": gate.reason,
                "used": gate.used,
                "limit": gate.limit,
            },
        )

    events: queue.Queue = queue.Queue()
    #: The worker owns the bundle; the background record needs it after the
    #: stream has closed. The terminal event is not enough — it deliberately
    #: omits `measured` and `build_log`, which is exactly the evidence worth
    #: keeping.
    produced: dict[str, Any] = {}

    def on_event(kind: str, data: dict) -> None:
        events.put((kind, data))

    def work() -> None:
        try:
            if intent == "explain":
                result = agent.explain(
                    request.message,
                    part=request.part,
                    history=request.history,
                    lens=request.lens,
                    on_event=on_event,
                )
                events.put(
                    (
                        "done",
                        {
                            "intent": "explain",
                            "success": result.get("success", False),
                            "answer": result.get("answer", ""),
                            "model": result.get("model", ""),
                            "error": result.get("error"),
                        },
                    )
                )
                return

            bundle = agent.design(request.message, on_event=on_event)
            produced["bundle"] = bundle
            if not bundle.get("success"):
                events.put(
                    (
                        "error",
                        {
                            "intent": "design",
                            "error": bundle.get("error")
                            or "the part could not be built",
                            "model": bundle.get("model", ""),
                            "verification": bundle.get("verification") or {},
                            "raw_completion": bundle.get("raw_completion"),
                        },
                    )
                )
                return
            events.put(
                (
                    "done",
                    {
                        "intent": "design",
                        "success": True,
                        "model": bundle.get("model", ""),
                        "part_class": bundle.get("part_class", ""),
                        "variables": bundle.get("variables", {}),
                        "blueprint": bundle.get("blueprint"),
                        # Assembled here rather than left to the client, so the
                        # part on screen has a history immediately — before it is
                        # saved, and without a second request. The same function
                        # serves GET /designs/{id}/feature-tree, so a live part
                        # and a reopened one cannot show different trees for the
                        # same geometry.
                        "feature_tree": _feature_tree_for(bundle),
                        # The readable account. `thinking` and `blueprint` stay in the
                        # payload untouched — they are the debugging record — but the
                        # UI leads with this.
                        "narrative": bundle.get("narrative"),
                        "thinking": bundle.get("thinking", ""),
                        "files": bundle.get("files", {}),
                        "stats": bundle.get("stats"),
                        "verification": bundle.get("verification") or {},
                        "generation_time_ms": bundle.get("generation_time_ms", 0),
                        "request_id": bundle.get("request_id", ""),
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            # The generator below is the only thing that can report to the
            # client, so every failure has to become an event or the stream
            # hangs until the timeout.
            logger.exception("studio_turn_failed")
            events.put(("error", {"error": str(exc)[:500]}))

    threading.Thread(target=work, daemon=True, name="studio-turn").start()

    if intent == "design":
        background.add_task(
            _record_when_finished, produced, request.message, gate.user_id
        )

    def stream():
        while True:
            try:
                kind, data = events.get(timeout=STREAM_TIMEOUT_S)
            except queue.Empty:
                yield _sse("error", {"error": "the worker stopped responding"})
                return
            yield _sse(kind, data)
            if kind in ("done", "error"):
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this, a proxy sitting in front of the app buffers the
            # whole stream and the user sees nothing until it completes.
            "X-Accel-Buffering": "no",
        },
    )


class AddFeatureRequest(BaseModel):
    """One operation appended by hand from the workbench."""

    type: str = Field(..., max_length=40)
    label: str = Field("", max_length=120)
    #: Dimensions this feature introduces, declared so ``parameters`` can name
    #: them. Keeping them named is what leaves a hand edit tunable afterwards.
    variables: dict[str, float] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: Profile for the operations that consume one (Pad, Pocket, Revolution,
    #: Groove): ``{"builder": "rect", "plane": "XY", "args": {...}}``.
    sketch: Optional[dict[str, Any]] = None


class RebuildRequest(BaseModel):
    """Rebuild an existing Blueprint, optionally edited by hand."""

    blueprint: dict[str, Any]
    #: New values for variables the Blueprint already declares.
    variables: dict[str, float] = Field(default_factory=dict)
    add_feature: Optional[AddFeatureRequest] = None


@router.post("/rebuild")
def studio_rebuild(
    request: RebuildRequest,
    background: BackgroundTasks,
    gate: StudioGate = Depends(studio_gate),
):
    """Rebuild a part from its Blueprint — no model call, no new design.

    This is the deterministic half of the studio: the parameter sliders and the
    workbench tools both land here. Nothing is generated, so nothing can drift;
    the same Blueprint and the same variables always produce the same solid.

    It is still metered. A rebuild is a FreeCAD container either way, and the
    kernel is the expensive part of a build, not the LLM.
    """
    from app.services import blueprint_edit, blueprint_service

    if not gate.known:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "sign in to rebuild this part",
                "reason": "authentication_required",
            },
        )
    if not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": gate.message or "monthly generation limit reached",
                "reason": gate.reason,
                "used": gate.used,
                "limit": gate.limit,
            },
        )

    original = request.blueprint
    if not original.get("template"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "this part has no Blueprint to rebuild from"},
        )

    try:
        edited = blueprint_edit.retune(original, request.variables)
        if request.add_feature:
            edited = blueprint_edit.append_feature(
                edited,
                request.add_feature.type,
                parameters=request.add_feature.parameters,
                variables=request.add_feature.variables,
                label=request.add_feature.label,
                sketch=request.add_feature.sketch,
            )
    except blueprint_edit.EditError as exc:
        # The edit never reached the kernel, so this is a 400 and not a failed
        # build — the distinction matters to the panel showing it.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"error": str(exc)}
        ) from exc

    bundle = blueprint_service.build_from_payload(edited)
    contract_broken = blueprint_edit.template_changed(original, edited)

    # Recorded on the same terms as a generated turn: geometry is what costs,
    # so a rebuild that produced a solid is charged and one that failed is not.
    background.add_task(
        _record_when_finished,
        {"bundle": bundle},
        f"rebuild: {bundle.get('part_class') or 'part'}",
        gate.user_id,
    )

    return {
        "success": bool(bundle.get("success")),
        "part_class": bundle.get("part_class", ""),
        "variables": bundle.get("variables", {}),
        "blueprint": bundle.get("blueprint"),
        "feature_tree": _feature_tree_for(bundle),
        "files": bundle.get("files", {}),
        "stats": bundle.get("stats"),
        # A hand-added feature puts the geometry outside what the model's
        # assertions describe. The verdict still travels, because the checks
        # that ran are worth seeing, but `contract_broken` tells the UI to stop
        # presenting it as a grade of *this* part.
        "verification": bundle.get("verification") or {},
        "contract_broken": contract_broken,
        "generation_time_ms": bundle.get("generation_time_ms", 0),
        "request_id": bundle.get("request_id", ""),
        "error": bundle.get("error"),
    }
