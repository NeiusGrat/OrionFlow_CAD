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

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.logging_config import get_logger

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


@router.get("/health")
def studio_health():
    """Which model and which builder this instance would actually use."""
    from app.services.studio_agent import get_studio_agent

    return get_studio_agent().health()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat")
def studio_chat(request: StudioChatRequest):
    """One studio turn: either design a part, or talk about the open one."""
    from app.services.studio_agent import get_studio_agent, _looks_like_a_question

    agent = get_studio_agent()

    intent = request.intent
    if intent not in ("design", "explain"):
        # No part open means there is nothing to discuss yet, so even a
        # question becomes a design request.
        intent = ("explain" if request.part and
                  _looks_like_a_question(request.message) else "design")

    events: queue.Queue = queue.Queue()

    def on_event(kind: str, data: dict) -> None:
        events.put((kind, data))

    def work() -> None:
        try:
            if intent == "explain":
                result = agent.explain(request.message, part=request.part,
                                       history=request.history,
                                       on_event=on_event)
                events.put(("done", {
                    "intent": "explain",
                    "success": result.get("success", False),
                    "answer": result.get("answer", ""),
                    "model": result.get("model", ""),
                    "error": result.get("error"),
                }))
                return

            bundle = agent.design(request.message, on_event=on_event)
            if not bundle.get("success"):
                events.put(("error", {
                    "intent": "design",
                    "error": bundle.get("error") or "the part could not be built",
                    "model": bundle.get("model", ""),
                    "verification": bundle.get("verification") or {},
                    "raw_completion": bundle.get("raw_completion"),
                }))
                return
            events.put(("done", {
                "intent": "design",
                "success": True,
                "model": bundle.get("model", ""),
                "part_class": bundle.get("part_class", ""),
                "variables": bundle.get("variables", {}),
                "blueprint": bundle.get("blueprint"),
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
            }))
        except Exception as exc:  # noqa: BLE001
            # The generator below is the only thing that can report to the
            # client, so every failure has to become an event or the stream
            # hangs until the timeout.
            logger.exception("studio_turn_failed")
            events.put(("error", {"error": str(exc)[:500]}))

    threading.Thread(target=work, daemon=True, name="studio-turn").start()

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
