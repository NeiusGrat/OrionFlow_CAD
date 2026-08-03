"""Design sessions: the studio route with a person in the middle.

``POST /studio/chat`` designs and builds in one breath. It stays exactly as it
is — it is live, it is metered, and there is no reason to disturb it. These
routes are the workflow beside it, for the case where the plan is worth reading
before a container starts:

    POST   /studio/sessions              prompt in; stops at the approval gate
    GET    /studio/sessions              the caller's sessions
    GET    /studio/sessions/{id}         state, current plan, full history
    POST   /studio/sessions/{id}/approve  a person says yes to one revision
    POST   /studio/sessions/{id}/reject   a person says no, with a reason
    POST   /studio/sessions/{id}/revise   a person asks for a change in words
    POST   /studio/sessions/{id}/build    builds the approved revision only
    POST   /studio/sessions/{id}/accept   final acceptance
    POST   /studio/sessions/{id}/cancel

Every refusal comes from ``app/domain/design_session.py`` as a typed error
carrying a stable ``reason``, so a client acts on the field rather than matching
on prose. Nothing here re-implements a rule: the routes resolve the caller,
call the service, and translate one exception type.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.domain.design_session import SessionError
from app.logging_config import get_logger
from app.services import design_sessions
from app.services.studio_persistence import StudioGate, studio_gate

logger = get_logger(__name__)
router = APIRouter(tags=["Design Sessions"])


def _require_user(gate: StudioGate):
    """Sessions are per-account by construction — there is no anonymous one.

    Both the design and the build call something we pay for, and a session is
    keyed to a user in the schema. An anonymous route here would be a way to
    spend the inference budget without limit and would have nowhere to store
    what it produced.
    """
    if not gate.known:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "sign in to design with OrionFlow",
                "reason": "authentication_required",
            },
        )
    return gate.user_id


def _refuse(exc: SessionError) -> HTTPException:
    """A domain refusal, as the status code it actually means.

    The gate raising ``NotApproved`` is a 403 and a stale revision is a 409;
    flattening both to 400 would leave a client unable to tell "you may not do
    this" from "the thing you are pointing at moved".
    """
    return HTTPException(status_code=exc.status, detail=exc.as_dict())


class CreateSessionRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=4000)


class DecisionRequest(BaseModel):
    #: Which revision is being decided on. Required: if a revision lands between
    #: the plan a user read and the decision they send, the decision must not
    #: silently transfer to a design they never saw.
    revision: int = Field(..., ge=1)
    note: str = Field("", max_length=2000)


class ReviseRequest(BaseModel):
    instruction: str = Field(..., min_length=3, max_length=2000)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest, gate: StudioGate = Depends(studio_gate)
):
    """Start a design. Proposes once, then stops.

    Metered like any design turn, because a proposal is a model call. The build
    is metered separately when it happens — with an approval in the middle, one
    session can produce several builds, and the quota follows the containers.
    """
    user_id = _require_user(gate)
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
    try:
        return await design_sessions.create(user_id, request.prompt)
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.get("")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200), gate: StudioGate = Depends(studio_gate)
):
    return {"items": await design_sessions.listing(_require_user(gate), limit)}


@router.get("/{session_id}")
async def get_session(session_id: str, gate: StudioGate = Depends(studio_gate)):
    user_id = _require_user(gate)
    try:
        return await design_sessions.get(user_id, _uuid(session_id))
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.post("/{session_id}/approve")
async def approve_session(
    session_id: str,
    request: DecisionRequest,
    gate: StudioGate = Depends(studio_gate),
):
    user_id = _require_user(gate)
    try:
        return await design_sessions.approve(
            user_id, _uuid(session_id), request.revision, request.note
        )
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.post("/{session_id}/reject")
async def reject_session(
    session_id: str,
    request: DecisionRequest,
    gate: StudioGate = Depends(studio_gate),
):
    user_id = _require_user(gate)
    try:
        return await design_sessions.reject(
            user_id, _uuid(session_id), request.revision, request.note
        )
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.post("/{session_id}/revise")
async def revise_session(
    session_id: str,
    request: ReviseRequest,
    gate: StudioGate = Depends(studio_gate),
):
    """A change asked for in words. Produces a new revision, pending approval."""
    user_id = _require_user(gate)
    if not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": gate.message or "monthly generation limit reached",
                "reason": gate.reason,
            },
        )
    try:
        return await design_sessions.revise(
            user_id, _uuid(session_id), request.instruction
        )
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.post("/{session_id}/build")
async def build_session(
    session_id: str,
    force: bool = Query(
        False,
        description="Rebuild a revision that has already been built. Never "
        "waives the approval or the Blueprint hash check.",
    ),
    gate: StudioGate = Depends(studio_gate),
):
    """Build the approved revision. Refuses anything that is not one.

    Idempotent: asking twice for the same revision returns the stored result
    rather than spending a second container, so a client that retries a timed
    out request gets its part back instead of being charged again.
    """
    user_id = _require_user(gate)
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
    try:
        return await design_sessions.build(user_id, _uuid(session_id), force=force)
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.get("/{session_id}/events")
async def stream_events(
    session_id: str,
    after: int = Query(0, ge=0, description="Last sequence number already seen."),
    gate: StudioGate = Depends(studio_gate),
):
    """Server-sent events for one session, resumable from a cursor.

    Replays everything after ``after`` and then follows. The cursor is the whole
    point: a refresh, a dropped connection or a phone waking up reconnects with
    the last ``seq`` it saw and misses nothing. A stream that only followed live
    would lose whatever happened while it was gone, and on a scale-to-zero host
    that is most of the interesting part.

    The stream ends when the session reaches a state where nothing further can
    happen without another request — awaiting approval, built, failed — rather
    than waiting on a human inside an HTTP connection. The client reconnects.
    """
    import json

    from fastapi.responses import StreamingResponse

    user_id = _require_user(gate)
    session_id_uuid = _uuid(session_id)

    # Resolved before the stream opens, so a caller who cannot see this session
    # gets a 404 rather than a 200 carrying an error event.
    try:
        await design_sessions.get_view(user_id, session_id_uuid)
    except SessionError as exc:
        raise _refuse(exc) from exc

    async def _stream():
        try:
            async for cursor, event in design_sessions.follow(
                user_id, session_id_uuid, after
            ):
                yield (
                    f"id: {cursor}\nevent: {event['type']}\n"
                    f"data: {json.dumps(event, default=str)}\n\n"
                )
        except SessionError as exc:
            yield f"event: error\ndata: {json.dumps(exc.as_dict())}\n\n"
        except Exception:  # noqa: BLE001
            logger.exception("session_stream_failed")
            yield 'event: error\ndata: {"error": "the stream stopped"}\n\n'

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this, a proxy buffers the whole stream and the client sees
            # nothing until it completes.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/accept")
async def accept_session(session_id: str, gate: StudioGate = Depends(studio_gate)):
    user_id = _require_user(gate)
    try:
        return await design_sessions.accept(user_id, _uuid(session_id))
    except SessionError as exc:
        raise _refuse(exc) from exc


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: str, gate: StudioGate = Depends(studio_gate)):
    user_id = _require_user(gate)
    try:
        return await design_sessions.cancel(user_id, _uuid(session_id))
    except SessionError as exc:
        raise _refuse(exc) from exc


def _uuid(value: str):
    """A malformed id is a 404, not a 500.

    Refused here rather than by a path converter so it cannot be told apart
    from a session belonging to someone else — both are "no such session".
    """
    import uuid as _u

    try:
        return _u.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no such design session", "reason": "not_found"},
        ) from None
