"""Design sessions: propose, decide, build — with the gate in code.

The rules live in ``app/domain/design_session.py`` and are pure. This module is
the part that touches the database and the agent, and it exists to keep two
promises the domain layer cannot keep on its own.

**No connection is held across a model call or a build.** Every function here
opens a short-lived session, does its writes, and closes it. A proposal takes
tens of seconds and a build takes minutes; a request-scoped connection spanning
either would exhaust the pool under a handful of concurrent designers, and the
symptom — database timeouts on login — is a very long way from the cause. This
is the same reasoning as ``studio_persistence.studio_gate``, and it is why the
routes below take no ``Depends(get_db)``.

**The gate is a function that raises, not a prompt that asks.** ``build`` calls
``authorize_build`` before anything reaches FreeCAD, and that check re-reads the
approval and the Blueprint hash from the row rather than trusting what the
caller sent. A client cannot approve its own build by posting the right JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

from app.domain.design_session import (
    TERMINAL,
    ApprovalState,
    BuildStatus,
    RevisionOrigin,
    SessionError,
    SessionState,
    authorize_build,
    can_transition,
    needs_reapproval,
    transition,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


class SessionNotFound(SessionError):
    reason = "not_found"
    status = 404


class RevisionNotFound(SessionError):
    reason = "revision_not_found"
    status = 404


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
async def _load(db, session_id: uuid.UUID, user_id: uuid.UUID):
    """The session, or a 404 — scoped by owner, never by id alone.

    The ownership predicate is part of the lookup rather than a check after it:
    a session id is a bearer token for someone's design history, and "load then
    compare" is the shape that grows a path where the comparison is forgotten.
    """
    from app.db.models import DesignSession

    found = await db.get(DesignSession, session_id)
    if found is None or found.user_id != user_id:
        raise SessionNotFound("no such design session", session_id=str(session_id))
    return found


async def _emit(db, session, kind: str, revision: Optional[int] = None, **data) -> None:
    """Append one event to the session's log.

    The sequence number is computed from what is already there rather than from
    a counter on the session row, so it stays correct if a write is retried. The
    unique constraint on (session_id, seq) is what makes a race collide loudly
    instead of producing two events with the same number — a cursor would skip
    one of them forever, and a silently missing event is a much worse failure
    than a retryable one.

    Never raises: an event is a record of something that already happened, and
    losing the record must not undo it.
    """
    from sqlalchemy import select

    from app.db.models import SessionEvent

    try:
        # Read the rows rather than asking the database for MAX(seq). Neither is
        # atomic against a concurrent append — the unique constraint is what
        # actually settles that — and a session accumulates tens of events, not
        # thousands, so the round trip buys nothing and the plain select keeps
        # the query surface small enough to reason about.
        result = await db.execute(
            select(SessionEvent).where(SessionEvent.session_id == session.id)
        )
        seq = max((e.seq for e in result.scalars().all()), default=0) + 1
        db.add(
            SessionEvent(
                session_id=session.id,
                seq=seq,
                type=kind,
                revision=revision if revision is not None else session.current_revision,
                data=data or {},
            )
        )
        # Flushed immediately, and this is load-bearing rather than tidy. Adding
        # only *stages* the row: it stays invisible to the SELECT above until it
        # reaches the database. Three events emitted in one transaction — which
        # is what creating a session does — therefore all read a maximum of zero
        # and all claimed seq 1, and the unique constraint rejected the whole
        # commit. The session came back as a 500 with nothing written.
        #
        # Worth noting where this was found: the in-memory fake used by the
        # tests modelled a database that flushes on add and could not reproduce
        # it. It only appeared against real Postgres.
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "session_event_write_failed",
            session_id=str(session.id),
            type=kind,
            error=repr(exc),
        )


async def events(db, session_id: uuid.UUID, after: int = 0) -> list[dict]:
    """Everything that happened after ``after``, oldest first."""
    from sqlalchemy import select

    from app.db.models import SessionEvent

    result = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id, SessionEvent.seq > after)
        .order_by(SessionEvent.seq)
    )
    return [
        {
            "seq": e.seq,
            "type": e.type,
            "revision": e.revision,
            "data": e.data or {},
            "at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars().all()
    ]


async def _revisions(db, session_id: uuid.UUID) -> list:
    from sqlalchemy import select

    from app.db.models import DesignRevision

    result = await db.execute(
        select(DesignRevision)
        .where(DesignRevision.session_id == session_id)
        .order_by(DesignRevision.number)
    )
    return list(result.scalars().all())


def _rehash(payload: Optional[dict]) -> Optional[str]:
    """Recompute the hash of a stored Blueprint. Never read it out of the row.

    The payload is the model's own output and carries no hash of its own —
    ``freeze()`` computes it — so there is nothing to read. That is the right
    way round: a self-declared hash would be edited by anything that edited the
    design, and the check would confirm only that the two lies agreed. Deriving
    it means the comparison against ``blueprint_hash`` (written at proposal
    time, before any person saw it) actually detects a changed design.

    Returns None when the stored Blueprint no longer freezes at all, which the
    gate treats as drift — correctly, since it cannot be the design that was
    approved.
    """
    from orion.blueprint import Blueprint, BlueprintError

    if not payload:
        return None
    try:
        return Blueprint.from_dict(payload).freeze().blueprint_hash
    except (BlueprintError, KeyError, TypeError, ValueError):
        return None


async def _revision(db, session_id: uuid.UUID, number: int):
    for rev in await _revisions(db, session_id):
        if rev.number == number:
            return rev
    raise RevisionNotFound(f"this session has no revision {number}", number=number)


# --------------------------------------------------------------------------- #
# proposing
# --------------------------------------------------------------------------- #
def _write_proposal(rev, proposal) -> None:
    """Copy a ``Proposal`` onto a revision row. One place, so nothing is lost."""
    rev.blueprint = proposal.payload
    rev.blueprint_hash = proposal.blueprint_hash
    rev.part_class = proposal.part_class
    rev.variables = proposal.variables
    rev.design_plan = proposal.design_plan
    rev.assertions = proposal.assertions
    rev.critique = proposal.critique
    rev.mechanical = proposal.mechanical
    rev.thinking = proposal.thinking
    rev.model = proposal.model


async def create(user_id: uuid.UUID, prompt: str) -> dict:
    """Start a session and propose once. Stops at the approval gate.

    The model call happens before any connection is opened, and on a worker
    thread — the agent's client is synchronous, and running it on the event loop
    would stall every other request for the length of a draw.
    """
    from app.db.models import DesignRevision, DesignSession
    from app.db.session import get_db_context
    from app.services.studio_agent import get_studio_agent

    agent = get_studio_agent()
    proposal = await run_in_threadpool(agent.propose, prompt)

    async with get_db_context() as db:
        session = DesignSession(
            user_id=user_id,
            original_prompt=prompt,
            state=SessionState.DRAFT,
            model=proposal.model or None,
        )
        db.add(session)
        await db.flush()

        if proposal.failure == "questions":
            # The request did not say enough. Its questions are the useful
            # answer — inventing the missing number is the failure the chain
            # exists to prevent — so no revision is written at all.
            session.state = transition(session.state, SessionState.QUESTIONS)
            session.open_questions = proposal.questions
            session.reasoning = proposal.reasoning
            await _emit(db, session, "session_created", 0, prompt=prompt)
            await _emit(db, session, "questions_required", 0,
                        questions=proposal.questions)
            await db.commit()
            return await _view(db, session)

        if not proposal.ok:
            session.state = transition(session.state, SessionState.FAILED)
            session.error = proposal.error
            await _emit(db, session, "session_created", 0, prompt=prompt)
            await _emit(db, session, "failed", 0, error=proposal.error)
            await db.commit()
            return await _view(db, session)

        rev = DesignRevision(
            session_id=session.id,
            number=1,
            origin=RevisionOrigin.MODEL,
            instruction=None,
        )
        _write_proposal(rev, proposal)
        db.add(rev)

        session.state = transition(session.state, SessionState.AWAITING_APPROVAL)
        session.current_revision = 1
        session.part_class = proposal.part_class
        session.reasoning = proposal.reasoning
        session.open_questions = []
        await _emit(db, session, "session_created", 1, prompt=prompt)
        await _emit(db, session, "plan_created", 1,
                    part_class=proposal.part_class,
                    blueprint_hash=proposal.blueprint_hash,
                    variables=proposal.variables,
                    critique_ok=bool((proposal.critique or {}).get("ok")))
        await _emit(db, session, "approval_required", 1)
        await db.commit()
        return await _view(db, session)


async def revise(
    user_id: uuid.UUID, session_id: uuid.UUID, instruction: str
) -> dict:
    """Ask for a change in words; get a new revision, pending approval.

    The previous revision is superseded, never edited. Whether the new one
    needs approval again is decided by what actually moved — see
    ``needs_reapproval``. Today every revision does, because it is a fresh draw
    from the model and the person has not seen it; the comparison is recorded on
    the row so a future automatic repair can use the same rule.
    """
    from app.db.models import DesignRevision
    from app.db.session import get_db_context
    from app.services.studio_agent import get_studio_agent

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        if session.state in (SessionState.COMPLETED, SessionState.CANCELLED):
            raise SessionError(
                "this session is closed", reason="closed", state=session.state.value
            )
        parent = await _revision(db, session.id, session.current_revision)
        # Everything the model needs is on the row, so the draw happens outside
        # this connection.
        parent_payload = dict(parent.blueprint or {})
        parent_number = parent.number
        parent_variables = dict(parent.variables or {})
        prompt = session.original_prompt
        next_number = max(r.number for r in await _revisions(db, session.id)) + 1

    agent = get_studio_agent()
    proposal = await run_in_threadpool(
        agent.redesign, prompt, parent_payload, instruction, next_number
    )

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        if not proposal.ok:
            session.state = transition(session.state, SessionState.FAILED)
            session.error = proposal.error
            await _emit(db, session, "failed", error=proposal.error)
            await db.commit()
            return await _view(db, session)

        parent = await _revision(db, session.id, parent_number)
        if parent.approval is ApprovalState.PENDING:
            parent.approval = ApprovalState.SUPERSEDED
            parent.decided_at = _now()

        material, reasons = needs_reapproval(parent_variables, proposal.variables)

        rev = DesignRevision(
            session_id=session.id,
            number=next_number,
            parent_number=parent_number,
            origin=RevisionOrigin.REVISION,
            instruction=instruction,
        )
        _write_proposal(rev, proposal)
        rev.decision_note = "; ".join(reasons) if material else None
        db.add(rev)

        session.state = _state_for_new_revision(session.state)
        session.current_revision = next_number
        session.part_class = proposal.part_class
        await _emit(db, session, "revision_created", next_number,
                    parent=parent_number, instruction=instruction,
                    blueprint_hash=proposal.blueprint_hash,
                    material_change=material, reasons=reasons)
        await _emit(db, session, "approval_required", next_number)
        await db.commit()
        return await _view(db, session)


def _state_for_new_revision(state: SessionState) -> SessionState:
    """Where a session lands when a new revision is proposed.

    ``awaiting_approval`` is deliberately not reachable from ``built`` or
    ``approved`` in one step: going straight there would replace a build result
    with no record that the design had been reopened. ``needs_revision`` is that
    record, so from those states the walk is two legal moves rather than one
    illegal one.

    From anywhere the move is already legal — ``needs_revision`` itself, a
    failed session, a session that stopped on questions — it is taken directly.
    Inserting the hop there would ask a state to transition to itself, which the
    table quite rightly refuses.
    """
    if state is SessionState.AWAITING_APPROVAL:
        return state
    if can_transition(state, SessionState.AWAITING_APPROVAL):
        return transition(state, SessionState.AWAITING_APPROVAL)
    return transition(
        transition(state, SessionState.NEEDS_REVISION),
        SessionState.AWAITING_APPROVAL,
    )


# --------------------------------------------------------------------------- #
# deciding
# --------------------------------------------------------------------------- #
async def approve(
    user_id: uuid.UUID, session_id: uuid.UUID, number: int, note: str = ""
) -> dict:
    """A person says yes to one specific revision.

    ``number`` is required rather than defaulting to the current revision: if a
    repair lands between the plan a user read and the approval they send, the
    approval must not silently transfer to a design they never saw.
    """
    from app.db.session import get_db_context

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        rev = await _revision(db, session.id, number)
        if rev.number != session.current_revision:
            raise SessionError(
                "revision {} is no longer the current one ({})".format(
                    number, session.current_revision
                ),
                reason="stale_revision",
                current=session.current_revision,
            )
        session.state = transition(session.state, SessionState.APPROVED)
        rev.approval = ApprovalState.APPROVED
        rev.decided_at = _now()
        rev.decision_note = note or rev.decision_note
        await _emit(db, session, "approval_received", number, note=note)
        await db.commit()
        return await _view(db, session)


async def reject(
    user_id: uuid.UUID, session_id: uuid.UUID, number: int, reason: str = ""
) -> dict:
    """A person says no and stops here.

    The reason is stored on the revision and kept forever. It is the one field
    in this schema no synthetic pipeline can produce, and the reason rejected
    revisions are not deleted.
    """
    from app.db.session import get_db_context

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        rev = await _revision(db, session.id, number)
        session.state = transition(session.state, SessionState.REJECTED)
        rev.approval = ApprovalState.REJECTED
        rev.decided_at = _now()
        rev.decision_note = reason
        await _emit(db, session, "rejected", number, reason=reason)
        await db.commit()
        return await _view(db, session)


async def accept(user_id: uuid.UUID, session_id: uuid.UUID) -> dict:
    """Final acceptance of the built part. The only state meaning a human was
    satisfied."""
    from app.db.session import get_db_context

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        session.state = transition(session.state, SessionState.COMPLETED)
        session.accepted_at = _now()
        await _emit(db, session, "completed")
        await db.commit()
        return await _view(db, session)


async def cancel(user_id: uuid.UUID, session_id: uuid.UUID) -> dict:
    from app.db.session import get_db_context

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        session.state = transition(session.state, SessionState.CANCELLED)
        await _emit(db, session, "cancelled")
        await db.commit()
        return await _view(db, session)


# --------------------------------------------------------------------------- #
# building
# --------------------------------------------------------------------------- #
async def build(
    user_id: uuid.UUID, session_id: uuid.UUID, force: bool = False
) -> dict:
    """Start the approved build and return immediately. Refuses anything else.

    The request no longer waits for FreeCAD. It authorises, claims the revision,
    hands the graph to the builder and comes back with ``state=building`` and a
    call id on the row. Two reasons, and the second is the one that forced it:

    * an approval means a person is in the loop, and a build can be asked for
      long after the plan was read — there is no request left to hold;
    * the API scales to zero. A build outliving its container was previously a
      lost build; now the result belongs to the builder until someone collects
      it, and any container can.

    The claim and the check share one transaction, so two concurrent requests
    cannot both pass the gate — the second finds ``building``, not ``approved``.
    """
    from app.db.session import get_db_context
    from app.services import blueprint_service

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)

        # Checked before the idempotency short-circuit below, not after. A
        # completed or cancelled session would otherwise skip the gate entirely
        # — the revision is already built, so the short-circuit returned 200 and
        # a client could reasonably read that as "your build was accepted" on a
        # design that was closed. Nothing was built either way; the status code
        # was simply lying about it.
        if session.state in TERMINAL:
            raise SessionError(
                "this session is closed",
                reason="closed",
                status=409,
                state=session.state.value,
            )

        rev = await _revision(db, session.id, session.current_revision)

        # Idempotent: an already-built revision is a result, not an error, so a
        # client that retries a timed-out request gets its part back.
        if rev.build_status is BuildStatus.BUILT and not force:
            return await _view(db, session)
        # Already in flight — the same answer as "started", because it was.
        if rev.build_status is BuildStatus.BUILDING and not force:
            return await _view(db, session)

        authorize_build(
            state=session.state,
            approval=rev.approval,
            build_status=rev.build_status,
            approved_hash=rev.blueprint_hash,
            blueprint_hash=_rehash(rev.blueprint),
            force=force,
        )

        payload = dict(rev.blueprint or {})
        request_id = uuid.uuid4().hex[:12]
        handle = await run_in_threadpool(
            blueprint_service.start_build, payload, request_id
        )

        if handle.get("error"):
            # Never reached the builder — a Blueprint that will not freeze, or
            # a build service that is down. Neither is a kernel failure and
            # neither leaves anything to collect.
            rev.build_status = BuildStatus.FAILED
            rev.build_error = str(handle["error"])[:2000]
            session.state = transition(session.state, SessionState.NEEDS_REVISION)
            session.error = rev.build_error
            await _emit(db, session, "failed", error=rev.build_error)
            await db.commit()
            return await _view(db, session)

        rev.request_id = request_id
        rev.build_call_id = handle.get("call_id") or None
        rev.build_status = BuildStatus.BUILDING
        rev.build_started_at = _now()
        session.state = transition(session.state, SessionState.BUILDING)
        await _emit(
            db, session, "build_started", request_id=request_id, forced=bool(force)
        )
        await db.commit()
        return await _view(db, session)


async def reconcile(user_id: uuid.UUID, session_id: uuid.UUID, wait: float = 0.0) -> dict:
    """Collect a finished build, if there is one. Safe to call at any time.

    This is how a result gets recorded without a worker process: every read of a
    building session tries to collect it. A client that never comes back costs
    nothing, because the result is held by the builder rather than by us, and
    the next request from anyone — a poll, a page load, the event stream —
    finishes the job. A session therefore cannot be permanently stranded by the
    container that started its build going away.

    Returns the session view either way; ``wait=0`` makes it a poll.
    """
    from app.db.session import get_db_context
    from app.services import blueprint_service

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        if session.state is not SessionState.BUILDING:
            return await _view(db, session)
        rev = await _revision(db, session.id, session.current_revision)
        if rev.build_status is not BuildStatus.BUILDING or not rev.build_call_id:
            return await _view(db, session)
        payload = dict(rev.blueprint or {})
        request_id = rev.request_id or ""
        call_id = rev.build_call_id
        number = rev.number
        prompt = session.original_prompt

    bundle = await run_in_threadpool(
        blueprint_service.collect_build, payload, request_id, call_id, wait
    )
    if bundle is None:
        return await get_view(user_id, session_id)

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        rev = await _revision(db, session.id, number)
        # Another caller collected it first. Their write stands; ours would be
        # identical, but re-running the transition would be illegal from the
        # state they left behind.
        if rev.build_status is not BuildStatus.BUILDING:
            return await _view(db, session)

        rev.verification = bundle.get("verification") or {}
        rev.stats = bundle.get("stats")
        rev.artifacts = bundle.get("files") or {}
        rev.build_error = (
            str(bundle.get("error"))[:2000] if bundle.get("error") else None
        )

        if bundle.get("success"):
            rev.build_status = BuildStatus.BUILT
            session.state = transition(session.state, SessionState.BUILT)
            await _emit(
                db,
                session,
                "build_completed",
                number,
                artifacts=sorted(rev.artifacts),
                request_id=request_id,
            )
            await _emit(
                db,
                session,
                "validation_completed",
                number,
                verdict=(rev.verification or {}).get("verdict", ""),
                checks=len((rev.verification or {}).get("checks") or []),
            )
            await _emit(db, session, "final_review_ready", number)
        else:
            rev.build_status = BuildStatus.FAILED
            # A failed build is not a dead session: the approved plan is still
            # there and a revision is the next move.
            session.state = transition(session.state, SessionState.NEEDS_REVISION)
            session.error = rev.build_error
            await _emit(db, session, "build_completed", number, error=rev.build_error)
        await db.commit()
        view = await _view(db, session)

    # Metering and the build record follow geometry, exactly as the chat route
    # does — one place decides what a build costs, and it is not this one.
    from app.services.studio_persistence import record_studio_build

    await record_studio_build(bundle, prompt, user_id)
    return view


async def get_view(user_id: uuid.UUID, session_id: uuid.UUID) -> dict:
    """The session as stored, with no attempt to collect anything."""
    from app.db.session import get_db_context

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        return await _view(db, session)


# --------------------------------------------------------------------------- #
# views
# --------------------------------------------------------------------------- #
def _revision_view(rev, full: bool = False) -> dict:
    out: dict[str, Any] = {
        "number": rev.number,
        "parent_number": rev.parent_number,
        "origin": rev.origin.value if rev.origin else None,
        "instruction": rev.instruction,
        "blueprint_hash": rev.blueprint_hash,
        "part_class": rev.part_class,
        "variables": rev.variables or {},
        "design_plan": rev.design_plan or {},
        "critique": rev.critique or {},
        "mechanical": rev.mechanical or {},
        "approval": rev.approval.value if rev.approval else None,
        "decision_note": rev.decision_note,
        "build_status": rev.build_status.value if rev.build_status else None,
        "request_id": rev.request_id,
        "verification": rev.verification or {},
        "stats": rev.stats,
        "artifacts": rev.artifacts or {},
        "build_error": rev.build_error,
        "created_at": rev.created_at.isoformat() if rev.created_at else None,
    }
    if full:
        # The Blueprint and the derivation are big and only the open revision
        # needs them; a history listing that carried every one of them would be
        # megabytes for a session with a few repairs.
        out["blueprint"] = rev.blueprint
        out["assertions"] = rev.assertions or []
        out["thinking"] = rev.thinking
        out["model"] = rev.model
    return out


async def _view(db, session) -> dict:
    """The whole session as a client sees it: state, plan, history."""
    revisions = await _revisions(db, session.id)
    current = next(
        (r for r in revisions if r.number == session.current_revision), None
    )
    return {
        "id": str(session.id),
        "state": session.state.value,
        "prompt": session.original_prompt,
        "part_class": session.part_class,
        "open_questions": session.open_questions or [],
        "reasoning": session.reasoning,
        "model": session.model,
        "error": session.error,
        "current_revision": session.current_revision,
        "revision": _revision_view(current, full=True) if current else None,
        "history": [_revision_view(r) for r in revisions],
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "accepted_at": session.accepted_at.isoformat() if session.accepted_at else None,
    }


async def get(user_id: uuid.UUID, session_id: uuid.UUID) -> dict:
    """The session — collecting a finished build on the way if there is one.

    Reads reconcile deliberately. Without a worker process, a request touching
    the session is the only thing that can notice a build has finished, so every
    read is one. It costs a non-blocking poll and it is what guarantees a
    session is never stranded by the container that started its build going
    away.
    """
    return await reconcile(user_id, session_id)


async def event_log(
    user_id: uuid.UUID, session_id: uuid.UUID, after: int = 0
) -> list[dict]:
    """The session's events after a cursor. Scoped by owner like everything else."""
    from app.db.session import get_db_context

    async with get_db_context() as db:
        session = await _load(db, session_id, user_id)
        return await events(db, session.id, after)


#: States in which nothing further will happen without another request. A stream
#: that kept polling past one of these would hold a connection open forever
#: waiting for a person.
SETTLED = frozenset(
    {
        SessionState.QUESTIONS,
        SessionState.AWAITING_APPROVAL,
        SessionState.BUILT,
        SessionState.NEEDS_REVISION,
        SessionState.COMPLETED,
        SessionState.REJECTED,
        SessionState.CANCELLED,
        SessionState.FAILED,
    }
)


async def follow(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    after: int = 0,
    poll_s: float = 2.0,
    budget_s: float = 240.0,
):
    """Yield ``(cursor, event)`` from ``after`` onwards, until the session settles.

    Replays first, then follows. Replaying is not an optimisation: a client that
    reconnects — a refresh, a dropped connection, a phone waking up — has to be
    able to catch up, and the cursor is what makes that possible without
    re-reading the whole session.

    Stops when the session reaches a state where nothing further will happen
    without another request, and in any case at ``budget_s``. Both matter on a
    host with a request timeout: a stream that waits forever for a person to
    approve something is a held connection with no one on the other end. The
    client reconnects with its cursor and loses nothing.
    """
    import asyncio
    import time

    cursor = after
    deadline = time.monotonic() + budget_s

    while True:
        view = await reconcile(user_id, session_id)
        for event in await event_log(user_id, session_id, cursor):
            cursor = event["seq"]
            yield cursor, event

        state = SessionState(view["state"])
        if state in SETTLED or time.monotonic() >= deadline:
            yield cursor, {"seq": cursor, "type": "idle", "data": {"state": state.value}}
            return
        await asyncio.sleep(poll_s)


async def listing(user_id: uuid.UUID, limit: int = 50) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import DesignSession
    from app.db.session import get_db_context

    async with get_db_context() as db:
        result = await db.execute(
            select(DesignSession)
            .where(DesignSession.user_id == user_id)
            .order_by(DesignSession.updated_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": str(s.id),
                "state": s.state.value,
                "prompt": s.original_prompt,
                "part_class": s.part_class,
                "current_revision": s.current_revision,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in result.scalars().all()
        ]
