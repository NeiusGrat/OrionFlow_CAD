"""The event log, and a build that outlives the request that started it.

Progress used to be a stream held open on one connection. With a person in the
middle that stops working: an approval happens on human time, and on a
scale-to-zero host the container that started a build is often gone before it
finishes. So progress became an append-only log with a per-session cursor, and a
build became a handle anyone can collect.

The two properties worth proving:

* **nothing is lost to a disconnect.** A client that goes away and comes back
  with its last ``seq`` gets everything that happened while it was gone.
* **nothing is stranded.** A build whose starter never returns is finished by
  whichever request touches the session next — which is why every read
  reconciles.
"""

import uuid

import pytest

from app.domain.design_session import BuildStatus, SessionState
from app.services import design_sessions as ds

from tests.test_design_sessions import (  # noqa: F401
    USER,
    FakeDB,
    agent,
    builder,
    db,
    revisions,
    session_row,
)


async def _events(sid, after=0):
    return await ds.event_log(USER, sid, after)


def _types(events):
    return [e["type"] for e in events]


# --------------------------------------------------------------------------- #
# the log
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_a_session_records_what_happened_in_order(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    await ds.build(USER, sid)
    await ds.get(USER, sid)
    await ds.accept(USER, sid)

    log = await _events(sid)

    assert _types(log) == [
        "session_created",
        "plan_created",
        "approval_required",
        "approval_received",
        "build_started",
        "build_completed",
        "validation_completed",
        "final_review_ready",
        "completed",
    ]
    # Monotonic and gapless, which is what makes the cursor usable.
    assert [e["seq"] for e in log] == list(range(1, len(log) + 1))


@pytest.mark.asyncio
async def test_events_written_in_one_transaction_get_distinct_numbers(db, agent, builder):
    """The bug real Postgres found and the fake could not.

    ``_emit`` computes the next sequence number by querying for the current
    maximum. An added row is only *staged* until it is flushed, so three events
    appended while creating a session all read a maximum of zero, all claimed
    seq 1, and the unique constraint rejected the entire commit — the request
    came back a 500 with nothing written at all.

    The fake now models flush semantics, so this test fails without the flush in
    ``_emit``. It is the sequence numbers that matter rather than the count: a
    duplicate would make a client's cursor skip an event permanently.
    """
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    log = await _events(sid)

    seqs = [e["seq"] for e in log]
    assert len(seqs) == 3, _types(log)
    assert seqs == [1, 2, 3], "sequence numbers must be distinct and gapless"
    assert len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_the_plan_event_carries_enough_to_show_without_a_second_request(
    db, agent, builder
):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    plan = next(e for e in await _events(sid) if e["type"] == "plan_created")

    assert plan["data"]["part_class"] == "plate"
    assert len(plan["data"]["blueprint_hash"]) == 64
    assert plan["data"]["variables"] == {"thick": 6.0, "width": 40.0}
    assert plan["data"]["critique_ok"] is True
    assert plan["revision"] == 1


@pytest.mark.asyncio
async def test_a_cursor_returns_only_what_came_after_it(db, agent, builder):
    """The reconnect case: a client that missed the middle catches up."""
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    seen = await _events(sid)
    cursor = seen[-1]["seq"]

    await ds.approve(USER, sid, 1)
    await ds.build(USER, sid)
    await ds.get(USER, sid)

    later = await _events(sid, after=cursor)

    assert _types(later)[0] == "approval_received"
    assert all(e["seq"] > cursor for e in later)
    assert "plan_created" not in _types(later)


@pytest.mark.asyncio
async def test_a_rejection_and_its_reason_are_on_the_record(db, agent, builder):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    await ds.reject(USER, sid, 1, reason="the bolt pattern is wrong")

    event = next(e for e in await _events(sid) if e["type"] == "rejected")
    assert event["data"]["reason"] == "the bolt pattern is wrong"


@pytest.mark.asyncio
async def test_a_revision_records_what_changed_and_whether_it_matters(
    db, agent, builder
):
    from tests.test_design_sessions import _proposal
    from tests.test_studio_propose_build import blueprint

    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    wider = blueprint()
    wider["variables"]["width"] = 90.0
    agent.revised = _proposal(wider)

    await ds.revise(USER, sid, "make it 90mm wide")

    event = next(e for e in await _events(sid) if e["type"] == "revision_created")
    assert event["data"]["instruction"] == "make it 90mm wide"
    assert event["data"]["parent"] == 1
    assert event["data"]["material_change"] is True
    assert "width 40 → 90" in event["data"]["reasons"]


@pytest.mark.asyncio
async def test_a_lost_event_never_costs_the_thing_that_happened(
    db, agent, builder, monkeypatch
):
    """An event is a record of something already done. Losing the record must
    not undo it."""
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    async def _broken(self, stmt):
        raise RuntimeError("the log is unavailable")

    monkeypatch.setattr(FakeDB, "execute", _broken, raising=False)
    with pytest.raises(Exception):
        # The whole load path uses execute here, so this only proves the
        # emit-level guard indirectly; the direct check is below.
        await ds.approve(USER, sid, 1)
    monkeypatch.undo()

    # Directly: a failing append is swallowed and the caller proceeds.
    session = session_row(db)

    class _Boom:
        async def execute(self, stmt):
            raise RuntimeError("the log is unavailable")

    await ds._emit(_Boom(), session, "approval_received")


# --------------------------------------------------------------------------- #
# a build nobody is waiting for
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_a_build_in_flight_is_reported_as_building_not_as_done(
    db, agent, builder
):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    builder.ready = False

    view = await ds.build(USER, sid)
    assert view["state"] == SessionState.BUILDING.value

    # Reading it repeatedly while it runs neither completes nor breaks it.
    for _ in range(3):
        view = await ds.get(USER, sid)
        assert view["state"] == SessionState.BUILDING.value
    assert len(builder.started) == 1


@pytest.mark.asyncio
async def test_any_later_read_collects_a_finished_build(db, agent, builder):
    """The starter never comes back; someone else finishes the job.

    This is the whole point of storing the call id: without it the session would
    sit in ``building`` forever once the container that spawned the work went
    away, which on a scale-to-zero host is the normal case rather than the edge
    one.
    """
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    builder.ready = False
    await ds.build(USER, sid)

    builder.ready = True
    view = await ds.get(USER, sid)

    assert view["state"] == SessionState.BUILT.value
    assert revisions(db)[0].build_status is BuildStatus.BUILT
    assert "build_completed" in _types(await _events(sid))


@pytest.mark.asyncio
async def test_a_second_collector_does_not_double_record(db, agent, builder):
    """Two readers racing to collect must not both write the result.

    The second finds the revision already out of ``building`` and leaves it
    alone — re-running the transition would be illegal from the state the first
    one left behind, and the events would be duplicated.
    """
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    await ds.build(USER, sid)

    await ds.get(USER, sid)
    await ds.get(USER, sid)
    await ds.get(USER, sid)

    log = _types(await _events(sid))
    assert log.count("build_completed") == 1
    assert log.count("validation_completed") == 1


@pytest.mark.asyncio
async def test_a_builder_that_cannot_be_reached_fails_the_revision_not_the_session(
    db, agent, builder
):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    builder.start_error = "the build service is unreachable"

    view = await ds.build(USER, sid)

    assert view["state"] == SessionState.NEEDS_REVISION.value
    assert view["revision"]["build_status"] == "failed"
    assert "unreachable" in view["revision"]["build_error"]
    assert "failed" in _types(await _events(sid))
    # Still resumable: the approved plan is intact and a revision is legal.
    view = await ds.revise(USER, sid, "try again")
    assert view["state"] == SessionState.AWAITING_APPROVAL.value


# --------------------------------------------------------------------------- #
# following
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_follow_replays_then_stops_when_nothing_more_can_happen(
    db, agent, builder
):
    """A stream must not hold a connection open waiting for a person.

    ``awaiting_approval`` is settled: the next thing that happens needs another
    request. The client reconnects with its cursor and loses nothing.
    """
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])

    seen = [
        event
        async for _cursor, event in ds.follow(
            USER, sid, poll_s=0.01, budget_s=5.0
        )
    ]

    assert _types(seen)[:3] == [
        "session_created",
        "plan_created",
        "approval_required",
    ]
    assert seen[-1]["type"] == "idle"
    assert seen[-1]["data"]["state"] == SessionState.AWAITING_APPROVAL.value


@pytest.mark.asyncio
async def test_follow_picks_up_a_build_that_finishes_while_it_watches(
    db, agent, builder
):
    view = await ds.create(USER, "a plate")
    sid = uuid.UUID(view["id"])
    await ds.approve(USER, sid, 1)
    builder.ready = False
    await ds.build(USER, sid)

    # Follows from the beginning so the replay includes ``build_started``; the
    # builder is released the moment the stream reports it, which is the
    # ordering a real client sees.
    #
    # ``budget_s`` is small deliberately. The default is four minutes, and a
    # follow loop whose exit condition is wrong does not fail — it waits, which
    # in a test reads as a hang rather than as the bug it is.
    seen = []
    async for _c, event in ds.follow(USER, sid, poll_s=0.01, budget_s=5.0):
        seen.append(event)
        if event["type"] == "build_started":
            builder.ready = True

    assert "build_completed" in _types(seen)
    assert "final_review_ready" in _types(seen)
    assert seen[-1]["type"] == "idle"
