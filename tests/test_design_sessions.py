"""The session workflow, end to end, against an in-memory database.

The rules themselves are proved in ``test_design_session_state.py`` without any
storage at all. What is left to show is that the service actually applies them —
that the gate is consulted before FreeCAD, that a build claims its revision
before it starts, and that the history is append-only.

The fake session below implements the small surface the service uses: ``get``,
``add``, ``flush``, ``commit``, and ``execute`` for single-table selects with
simple equality filters. It is deliberately not a database — it exists so the
workflow can be exercised without Postgres, and the one thing it must get right
is the filtering, because a fake that ignored ``WHERE user_id`` would let a
cross-account leak pass.
"""

import uuid

import pytest

from app.domain.design_session import (
    ApprovalState,
    BuildStatus,
    SessionState,
)
from app.services import design_sessions as ds


# --------------------------------------------------------------------------- #
# a database that fits in a dict
# --------------------------------------------------------------------------- #
def _apply_defaults(obj) -> None:
    """Python-side column defaults, which a real session applies at flush."""
    for col in type(obj).__table__.columns:
        if getattr(obj, col.key, None) is not None or col.default is None:
            continue
        arg = col.default.arg
        if callable(arg):
            try:
                value = arg()
            except TypeError:
                value = arg(None)
        else:
            value = arg
        setattr(obj, col.key, value)


def _predicates(stmt) -> list:
    """``WHERE`` as a list of (column, operator, value).

    The operator is carried rather than assumed. An earlier version of this
    helper collected equality pairs only, which silently turned ``seq > cursor``
    into ``seq == cursor`` and made the event cursor look broken when it was
    fine. A fake that quietly changes the meaning of a query is worse than no
    fake, because the test still runs and still asserts something — just not
    what it claims to.
    """
    from sqlalchemy.sql.elements import BinaryExpression

    where = stmt.whereclause
    if where is None:
        return []
    found = []
    for clause in getattr(where, "clauses", [where]):
        if isinstance(clause, BinaryExpression):
            try:
                found.append((clause.left.name, clause.operator, clause.right.value))
            except AttributeError:
                pass
    return found


def _holds(actual, op, value) -> bool:
    """Apply one SQL comparison in Python. Unknown operators match nothing.

    Refusing an operator this fake does not implement is deliberate: returning
    everything would make a query look like it matched when it was never
    evaluated, which is the failure mode the whole helper exists to avoid.
    """
    if actual is None:
        return False
    try:
        return bool(op(actual, value))
    except TypeError:
        return False


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeDB:
    """One store, shared by every context this test opens.

    Rows added are **pending** until flushed, because that is what SQLAlchemy
    does and the difference is not academic. An earlier version made an added
    row visible to the very next query, which models a database that flushes on
    add — no such database exists. Under it, three events appended in one
    transaction each read the same maximum sequence number and each claimed the
    same one, and the suite was perfectly happy. Real Postgres rejected the
    commit on the unique constraint and the request came back a 500.
    """

    def __init__(self, store: dict):
        self.store = store
        self.pending: list = []

    def add(self, obj):
        _apply_defaults(obj)
        self.pending.append(obj)

    async def flush(self):
        for obj in self.pending:
            _apply_defaults(obj)
            self.store.setdefault(type(obj), []).append(obj)
        self.pending.clear()

    async def commit(self):
        await self.flush()

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def get(self, model, pk):
        return next((o for o in self.store.get(model, []) if o.id == pk), None)

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        rows = list(self.store.get(entity, []))
        for name, op, value in _predicates(stmt):
            rows = [r for r in rows if _holds(getattr(r, name, None), op, value)]
        return _Result(rows)


@pytest.fixture
def db(monkeypatch):
    """Point the service at the in-memory store; hand the store back."""
    from contextlib import asynccontextmanager

    import app.db.session as db_session

    store: dict = {}

    @asynccontextmanager
    async def _ctx():
        yield FakeDB(store)

    monkeypatch.setattr(db_session, "get_db_context", _ctx)
    return store


def revisions(store) -> list:
    from app.db.models import DesignRevision

    return sorted(store.get(DesignRevision, []), key=lambda r: r.number)


def session_row(store):
    from app.db.models import DesignSession

    return store[DesignSession][0]


# --------------------------------------------------------------------------- #
# an agent that designs without a model or a kernel
# --------------------------------------------------------------------------- #
from tests.test_studio_propose_build import blueprint  # noqa: E402


def _proposal(payload=None, **over):
    from orion.blueprint import Blueprint
    from app.services.studio_agent import Proposal, critique

    payload = payload or blueprint()
    bp = Blueprint.from_dict(payload).freeze()
    fields = dict(
        ok=True,
        payload=payload,
        blueprint_hash=bp.blueprint_hash,
        part_class=bp.part_class,
        variables=dict(bp.variables),
        design_plan=dict(bp.design_plan),
        assertions=list(bp.assertions),
        critique=critique(bp, payload),
        thinking="a 40mm plate",
        model="orionflow",
    )
    fields.update(over)
    return Proposal(**fields)


class FakeAgent:
    def __init__(self):
        self.proposal = _proposal()
        self.revised = _proposal()

    def propose(self, prompt, on_event=None):
        return self.proposal

    def redesign(self, prompt, previous, instruction, attempt=1, on_event=None):
        return self.revised


class FakeBuilder:
    """Stands in for ``blueprint_service``: starts and collects, never builds.

    ``ready`` is the switch these tests need most — a build that has been
    started but has not finished is the state the whole asynchronous path exists
    to represent, and it was not previously reachable at all.
    """

    def __init__(self):
        self.started: list = []
        self.ready = True
        self.result = None
        self.start_error = None

    def start_build(self, payload, request_id=None):
        self.started.append(request_id)
        if self.start_error:
            return {"request_id": request_id, "call_id": "", "error": self.start_error}
        return {"request_id": request_id, "call_id": f"fc-{request_id}", "error": None}

    def collect_build(self, payload, request_id, call_id, wait=0.0):
        if not self.ready:
            return None
        if self.result is not None:
            return self.result
        return {
            "success": True,
            "request_id": request_id,
            "blueprint": payload,
            "files": {
                "fcstd": f"/api/v1/artifacts/{request_id}/part.FCStd",
                "step": f"/api/v1/artifacts/{request_id}/part.step",
            },
            "stats": {"volume_mm3": 9600.0},
            "verification": {"verdict": "verified", "checks": []},
            "error": None,
        }


@pytest.fixture
def builder(monkeypatch):
    fake = FakeBuilder()
    import app.services.blueprint_service as bs

    monkeypatch.setattr(bs, "start_build", fake.start_build)
    monkeypatch.setattr(bs, "collect_build", fake.collect_build)
    return fake


@pytest.fixture
def agent(monkeypatch):
    fake = FakeAgent()
    import app.services.studio_agent as sa

    monkeypatch.setattr(sa, "get_studio_agent", lambda: fake)

    async def _no_metering(bundle, prompt, user_id):
        return None

    import app.services.studio_persistence as sp

    monkeypatch.setattr(sp, "record_studio_build", _no_metering)
    return fake


USER = uuid.uuid4()


# --------------------------------------------------------------------------- #
# propose → approve → build → accept
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_a_prompt_stops_at_the_approval_gate(db, agent, builder):
    view = await ds.create(USER, "a 40mm square plate 6mm thick")

    assert view["state"] == SessionState.AWAITING_APPROVAL.value
    assert view["current_revision"] == 1
    assert view["revision"]["blueprint_hash"] == agent.proposal.blueprint_hash
    assert view["revision"]["approval"] == "pending"
    assert view["revision"]["build_status"] == "not_built"
    assert builder.started == [], "nothing may be built before a person decides"


@pytest.mark.asyncio
async def test_building_before_approval_is_refused(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    with pytest.raises(ds.SessionError) as exc:
        await ds.build(USER, sid)

    assert exc.value.reason == "approval_required"
    assert exc.value.status == 403
    assert builder.started == []
    # And the refusal left the session exactly where it was.
    assert session_row(db).state is SessionState.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_approval_allows_exactly_one_build(db, agent, builder):
    """The build starts and the request returns; a later read collects it."""
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    await ds.approve(USER, sid, 1, note="looks right")
    builder.ready = False
    view = await ds.build(USER, sid)

    # The request came back without waiting for FreeCAD.
    assert view["state"] == SessionState.BUILDING.value
    assert view["revision"]["build_status"] == "building"
    assert len(builder.started) == 1

    # Asking again while it is in flight does not start a second one.
    await ds.build(USER, sid)
    assert len(builder.started) == 1, "a build already running is not restarted"

    builder.ready = True
    view = await ds.get(USER, sid)

    assert view["state"] == SessionState.BUILT.value
    assert view["revision"]["build_status"] == "built"
    assert view["revision"]["artifacts"]["fcstd"].endswith("part.FCStd")
    assert view["revision"]["verification"]["verdict"] == "verified"

    # And a retry after it landed returns the stored result.
    again = await ds.build(USER, sid)
    assert len(builder.started) == 1, "a repeat build must be idempotent"
    assert again["revision"]["request_id"] == view["revision"]["request_id"]


@pytest.mark.asyncio
async def test_a_blueprint_edited_after_approval_is_refused(db, agent, builder):
    """The approval names a hash. Change the design and it no longer covers it."""
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)

    rev = revisions(db)[0]
    rev.blueprint = {**rev.blueprint, "variables": {"thick": 6.0, "width": 80.0}}

    with pytest.raises(ds.SessionError) as exc:
        await ds.build(USER, sid)

    assert exc.value.reason == "blueprint_drifted"
    assert builder.started == []


@pytest.mark.asyncio
async def test_final_acceptance_completes_the_session(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    await ds.build(USER, sid)
    await ds.get(USER, sid)

    view = await ds.accept(USER, sid)

    assert view["state"] == SessionState.COMPLETED.value
    assert view["accepted_at"] is not None


# --------------------------------------------------------------------------- #
# revisions
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_a_closed_session_refuses_a_build_rather_than_returning_one(
    db, agent, builder
):
    """A completed session must not accept a build verb.

    The idempotency short-circuit sits early on purpose — a retried request
    should get its part back rather than a second container. But it used to run
    *before* the state was examined, so a completed session skipped the gate
    entirely and answered 200. Nothing was built either way; the status code was
    simply lying about it, and a client could reasonably read it as acceptance.
    """
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    await ds.build(USER, sid)
    await ds.get(USER, sid)
    await ds.accept(USER, sid)

    with pytest.raises(ds.SessionError) as exc:
        await ds.build(USER, sid)

    assert exc.value.reason == "closed"
    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_a_revision_supersedes_rather_than_edits(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    agent.revised = _proposal(blueprint(guard="width - 5"))

    view = await ds.revise(USER, sid, "make the guard less aggressive")

    rows = revisions(db)
    assert [r.number for r in rows] == [1, 2]
    assert rows[0].approval is ApprovalState.SUPERSEDED, "the old one is kept"
    assert rows[0].blueprint is not None, "and keeps its Blueprint"
    assert rows[1].parent_number == 1
    assert rows[1].instruction == "make the guard less aggressive"
    assert view["state"] == SessionState.AWAITING_APPROVAL.value
    assert view["current_revision"] == 2


@pytest.mark.asyncio
async def test_a_revision_after_a_build_needs_approval_again(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    await ds.build(USER, sid)
    await ds.get(USER, sid)

    view = await ds.revise(USER, sid, "make it 80mm wide")

    assert view["state"] == SessionState.AWAITING_APPROVAL.value
    assert view["revision"]["approval"] == "pending"
    # And the new revision cannot be built on the strength of the old approval.
    with pytest.raises(ds.SessionError) as exc:
        await ds.build(USER, sid)
    assert exc.value.reason == "approval_required"


@pytest.mark.asyncio
async def test_approving_a_stale_revision_is_refused(db, agent, builder):
    """A revision landing between the plan a user read and the approval they
    send must not transfer that approval to a design they never saw."""
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.revise(USER, sid, "wider")

    with pytest.raises(ds.SessionError) as exc:
        await ds.approve(USER, sid, 1)

    assert exc.value.reason == "stale_revision"


@pytest.mark.asyncio
async def test_a_rejection_keeps_the_revision_and_its_reason(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    view = await ds.reject(USER, sid, 1, reason="the bolt pattern is wrong")

    assert view["state"] == SessionState.REJECTED.value
    rows = revisions(db)
    assert len(rows) == 1
    assert rows[0].approval is ApprovalState.REJECTED
    assert rows[0].decision_note == "the bolt pattern is wrong"
    assert rows[0].blueprint is not None


# --------------------------------------------------------------------------- #
# failures and questions
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_an_underspecified_request_asks_instead_of_designing(db, agent, builder):
    from app.services.studio_agent import Proposal

    agent.proposal = Proposal(
        failure="questions",
        error="what radial load must it carry?",
        questions=["what radial load must it carry?"],
        reasoning={"stopped_at": "select_component"},
    )

    view = await ds.create(USER, "a bearing housing")

    assert view["state"] == SessionState.QUESTIONS.value
    assert view["open_questions"] == ["what radial load must it carry?"]
    assert view["revision"] is None, "no revision for a design that was not made"
    assert revisions(db) == []


@pytest.mark.asyncio
async def test_a_failed_build_leaves_the_session_revisable(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    builder.result = {
        "success": False,
        "request_id": "0123456789ab",
        "error": "the kernel did not converge within 180s",
        "verification": {},
        "files": {},
    }

    await ds.build(USER, sid)
    view = await ds.get(USER, sid)

    assert view["state"] == SessionState.NEEDS_REVISION.value
    assert view["revision"]["build_status"] == "failed"
    assert "did not converge" in view["revision"]["build_error"]
    # Resumable: a revision is the next move and it is a legal one.
    view = await ds.revise(USER, sid, "simplify the pocket")
    assert view["state"] == SessionState.AWAITING_APPROVAL.value


# --------------------------------------------------------------------------- #
# ownership
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_another_account_cannot_see_or_touch_a_session(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    intruder = uuid.uuid4()

    for call in (
        ds.get(intruder, sid),
        ds.approve(intruder, sid, 1),
        ds.build(intruder, sid),
        ds.revise(intruder, sid, "wider"),
        ds.accept(intruder, sid),
    ):
        with pytest.raises(ds.SessionError) as exc:
            await call
        # Indistinguishable from a session that does not exist, deliberately.
        assert exc.value.reason == "not_found"

    assert session_row(db).state is SessionState.AWAITING_APPROVAL
    assert builder.started == []


@pytest.mark.asyncio
async def test_the_build_claims_its_revision_before_the_kernel_runs(
    db, agent, builder
):
    """The claim and the check share one transaction.

    A second request therefore finds ``building`` rather than ``approved`` and
    cannot start a rival container against the same revision. The call id is
    what makes the claim collectable afterwards — without it a session that
    outlived its container would be stranded in ``building`` forever.
    """
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    builder.ready = False

    await ds.build(USER, sid)

    assert session_row(db).state is SessionState.BUILDING
    assert revisions(db)[0].build_status is BuildStatus.BUILDING
    assert revisions(db)[0].build_call_id
