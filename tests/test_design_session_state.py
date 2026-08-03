"""The rules a design session obeys — asserted without a database.

Everything here is a predicate over values, which is the point of keeping
``app/domain/design_session.py`` free of SQLAlchemy: the gate that decides
whether a build may happen is the single most important rule in the product, and
it should be provable in milliseconds rather than only observable through a
route, a session and a Postgres.

The property this file exists for: **a build cannot happen without an approval
that names the exact Blueprint being built.** Not "the session was approved once"
— the revision, the hash, and the fact it has not already been built.
"""

import pytest

from app.domain.design_session import (
    TERMINAL,
    TRANSITIONS,
    AlreadyBuilt,
    ApprovalState,
    BlueprintDrifted,
    BuildStatus,
    InvalidTransition,
    NotApproved,
    SessionState,
    authorize_build,
    can_transition,
    needs_reapproval,
    transition,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


# --------------------------------------------------------------------------- #
# the transition table
# --------------------------------------------------------------------------- #
def test_every_state_has_an_entry():
    """A state missing from the table is not "no moves allowed", it is a state
    nobody thought about — and it would silently freeze any session reaching
    it."""
    assert set(TRANSITIONS) == set(SessionState)


def test_terminal_states_go_nowhere():
    for state in TERMINAL:
        assert TRANSITIONS[state] == frozenset(), state


def test_a_failed_session_is_resumable():
    """Most failures are transient — a dead endpoint, a kernel timeout. Losing
    the session with them would throw away a plan the user already approved."""
    assert SessionState.FAILED not in TERMINAL
    assert can_transition(SessionState.FAILED, SessionState.APPROVED)
    assert can_transition(SessionState.FAILED, SessionState.AWAITING_APPROVAL)


def test_the_happy_path_walks_end_to_end():
    state = SessionState.DRAFT
    for nxt in (
        SessionState.AWAITING_APPROVAL,
        SessionState.APPROVED,
        SessionState.BUILDING,
        SessionState.BUILT,
        SessionState.COMPLETED,
    ):
        state = transition(state, nxt)
    assert state is SessionState.COMPLETED


def test_a_session_cannot_skip_the_approval_gate():
    """The transition table alone must make the shortcut impossible."""
    assert not can_transition(SessionState.DRAFT, SessionState.BUILDING)
    assert not can_transition(SessionState.AWAITING_APPROVAL, SessionState.BUILDING)
    assert not can_transition(SessionState.AWAITING_APPROVAL, SessionState.BUILT)
    with pytest.raises(InvalidTransition):
        transition(SessionState.AWAITING_APPROVAL, SessionState.BUILDING)


def test_a_built_part_cannot_be_replaced_without_reopening_the_design():
    """``built → awaiting_approval`` would swap a result out with nothing
    recording that the design had been reopened. ``needs_revision`` is that
    record."""
    assert not can_transition(SessionState.BUILT, SessionState.AWAITING_APPROVAL)
    assert can_transition(SessionState.BUILT, SessionState.NEEDS_REVISION)
    assert can_transition(SessionState.NEEDS_REVISION, SessionState.AWAITING_APPROVAL)


def test_a_completed_session_is_closed_for_good():
    for target in SessionState:
        assert not can_transition(SessionState.COMPLETED, target)


def test_a_refused_transition_says_what_was_allowed():
    with pytest.raises(InvalidTransition) as exc:
        transition(SessionState.DRAFT, SessionState.COMPLETED)
    detail = exc.value.as_dict()
    assert detail["reason"] == "invalid_transition"
    assert detail["current"] == "draft"
    assert "awaiting_approval" in detail["allowed"]


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
def _authorize(**over):
    kw = dict(
        state=SessionState.APPROVED,
        approval=ApprovalState.APPROVED,
        build_status=BuildStatus.NOT_BUILT,
        approved_hash=HASH_A,
        blueprint_hash=HASH_A,
    )
    kw.update(over)
    return authorize_build(**kw)


def test_an_approved_revision_may_be_built():
    assert _authorize() is None


@pytest.mark.parametrize(
    "state",
    [s for s in SessionState if s is not SessionState.APPROVED],
)
def test_no_other_state_may_build(state):
    """Exhaustive on purpose. A gate that holds for the states someone
    remembered to test is not a gate."""
    with pytest.raises(NotApproved):
        _authorize(state=state)


@pytest.mark.parametrize(
    "approval",
    [a for a in ApprovalState if a is not ApprovalState.APPROVED],
)
def test_the_revision_itself_must_carry_the_approval(approval):
    """Approving revision 2 must not authorise building revision 3."""
    with pytest.raises(NotApproved):
        _authorize(approval=approval)


def test_a_blueprint_that_changed_after_approval_is_refused():
    """The whole basis of "you are building what was approved"."""
    with pytest.raises(BlueprintDrifted) as exc:
        _authorize(blueprint_hash=HASH_B)
    assert exc.value.reason == "blueprint_drifted"


def test_a_revision_with_no_frozen_blueprint_is_refused():
    with pytest.raises(BlueprintDrifted):
        _authorize(approved_hash=None)
    with pytest.raises(BlueprintDrifted):
        _authorize(blueprint_hash="")


def test_a_second_build_of_the_same_revision_is_refused():
    with pytest.raises(AlreadyBuilt):
        _authorize(build_status=BuildStatus.BUILT)


def test_force_rebuilds_but_never_waives_the_approval():
    """A deliberate rebuild is legitimate; a forced build of an unapproved or
    drifted design is not, and force must not become a way to get one."""
    assert _authorize(build_status=BuildStatus.BUILT, force=True) is None

    with pytest.raises(NotApproved):
        _authorize(approval=ApprovalState.PENDING, force=True)
    with pytest.raises(BlueprintDrifted):
        _authorize(blueprint_hash=HASH_B, force=True)


# --------------------------------------------------------------------------- #
# what counts as a material change
# --------------------------------------------------------------------------- #
def test_an_unchanged_design_needs_no_new_approval():
    needed, reasons = needs_reapproval({"w": 40.0}, {"w": 40.0})
    assert needed is False and reasons == []


def test_a_tiny_correction_does_not_interrupt_anyone():
    """A repair nudging a dimension to satisfy a guard is the system working.
    Asking a person about it trains them to approve without reading."""
    needed, _ = needs_reapproval({"w": 40.0}, {"w": 40.5})
    assert needed is False


def test_a_dimension_that_moves_materially_needs_a_new_approval():
    needed, reasons = needs_reapproval({"w": 40.0}, {"w": 80.0})
    assert needed is True
    assert reasons == ["w 40 → 80"]


def test_adding_or_dropping_a_dimension_is_always_material():
    needed, reasons = needs_reapproval({"w": 40.0}, {"w": 40.0, "hole_d": 6.0})
    assert needed is True and "new dimensions: hole_d" in reasons

    needed, reasons = needs_reapproval({"w": 40.0, "hole_d": 6.0}, {"w": 40.0})
    assert needed is True and "dimensions removed: hole_d" in reasons


def test_the_reasons_are_specific_enough_to_show_someone():
    """"This needs your approval again" without saying what moved is a dialog
    people click through."""
    _, reasons = needs_reapproval(
        {"w": 40.0, "t": 6.0}, {"w": 90.0, "t": 6.0, "r": 2.0}
    )
    assert "new dimensions: r" in reasons
    assert "w 40 → 90" in reasons
    assert not any("t" == r for r in reasons)
