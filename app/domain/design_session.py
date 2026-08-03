"""The rules a design session obeys, with nothing else attached.

A studio turn used to be a single HTTP request: prompt in, geometry out, and
whatever the model decided was what got built. That works right up until a
person needs to look at the plan first — and then it does not work at all,
because there is no such thing as "the design, before it was built". This module
gives that thing a shape.

Two rules carry the weight, and both are enforced here rather than in a prompt:

**A build requires an approval, and the approval names a hash.** Not "the
session was approved at some point" — the specific revision, identified by the
sha256 ``Blueprint.freeze`` computed before FreeCAD was ever involved. An
instruction telling a model to ask permission is a suggestion; a function that
raises is a gate.

**A revision is never edited, only superseded.** Rejected and superseded
revisions stay in the history with their critiques and their build results
attached. They are not clutter — a design that was proposed, judged wrong by a
person, and replaced is a more valuable record than the one that survived, and
it is the only place the reason a human said no is written down.

Deliberately free of SQLAlchemy, FastAPI and anything that does I/O: these are
predicates over values, so they can be exhaustively tested without a database
and cannot quietly start depending on one.
"""

from __future__ import annotations

import enum
from typing import Any, Optional


class SessionState(str, enum.Enum):
    """Where a session is resting.

    Every member is a state a session can sit in between two HTTP requests.
    There is deliberately no ``proposing`` or ``validating``: a state that only
    exists inside one request cannot be resumed, and a row stuck in one is
    indistinguishable from a live one.
    """

    #: Created; nothing has been proposed yet.
    DRAFT = "draft"
    #: The reasoning chain stopped — the request does not say enough to design
    #: from, and the questions are the answer. Not a failure.
    QUESTIONS = "questions"
    #: A revision exists and a person has to decide about it.
    AWAITING_APPROVAL = "awaiting_approval"
    #: Approved and not yet built. The only state a build may start from.
    APPROVED = "approved"
    #: A build is in flight against the approved revision.
    BUILDING = "building"
    #: Geometry exists and has been graded — verified or refused, both are built.
    BUILT = "built"
    #: The result was rejected, failed verification, or the user asked for
    #: changes. A new revision is expected.
    NEEDS_REVISION = "needs_revision"

    #: Terminal.
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    #: Not terminal: a failure is resumable, because most of them are transient
    #: (a dead endpoint, a kernel timeout) and losing the session with them
    #: would throw away the plan a user already approved.
    FAILED = "failed"


class ApprovalState(str, enum.Enum):
    """A single revision's standing with the person reviewing it."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    #: A newer revision replaced it before it was decided on.
    SUPERSEDED = "superseded"


class BuildStatus(str, enum.Enum):
    NOT_BUILT = "not_built"
    BUILDING = "building"
    BUILT = "built"
    FAILED = "failed"


class RevisionOrigin(str, enum.Enum):
    """Why this revision exists — the spine of a session's history."""

    #: The first draw from the prompt.
    MODEL = "model"
    #: An automatic repair after a failed build or a failed check.
    REPAIR = "repair"
    #: A person asked for a change in words.
    REVISION = "revision"
    #: A person changed variables directly (the parameter sliders).
    RETUNE = "retune"


TERMINAL: frozenset[SessionState] = frozenset(
    {SessionState.COMPLETED, SessionState.REJECTED, SessionState.CANCELLED}
)

#: What may follow what. Everything not listed is refused.
TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.DRAFT: frozenset(
        {
            SessionState.AWAITING_APPROVAL,
            SessionState.QUESTIONS,
            SessionState.FAILED,
            SessionState.CANCELLED,
        }
    ),
    # Answering the questions re-proposes; the session goes back through draft
    # rather than jumping straight to a plan, so the answer is on the record as
    # a new proposal and not as an edit to a stopped one.
    SessionState.QUESTIONS: frozenset(
        {
            SessionState.DRAFT,
            SessionState.AWAITING_APPROVAL,
            SessionState.CANCELLED,
            SessionState.FAILED,
        }
    ),
    SessionState.AWAITING_APPROVAL: frozenset(
        {
            SessionState.APPROVED,
            SessionState.REJECTED,
            SessionState.NEEDS_REVISION,
            SessionState.CANCELLED,
            SessionState.FAILED,
        }
    ),
    # A user may still change their mind after approving and before building.
    SessionState.APPROVED: frozenset(
        {
            SessionState.BUILDING,
            SessionState.NEEDS_REVISION,
            SessionState.CANCELLED,
            SessionState.FAILED,
        }
    ),
    SessionState.BUILDING: frozenset(
        {
            SessionState.BUILT,
            SessionState.NEEDS_REVISION,
            SessionState.FAILED,
            SessionState.CANCELLED,
        }
    ),
    SessionState.BUILT: frozenset(
        {
            SessionState.COMPLETED,
            SessionState.NEEDS_REVISION,
            SessionState.CANCELLED,
        }
    ),
    SessionState.NEEDS_REVISION: frozenset(
        {
            SessionState.AWAITING_APPROVAL,
            SessionState.QUESTIONS,
            SessionState.CANCELLED,
            SessionState.FAILED,
        }
    ),
    # Resumable: a new proposal, or an approved revision built again.
    SessionState.FAILED: frozenset(
        {
            SessionState.AWAITING_APPROVAL,
            SessionState.NEEDS_REVISION,
            SessionState.APPROVED,
            SessionState.CANCELLED,
        }
    ),
    SessionState.COMPLETED: frozenset(),
    SessionState.REJECTED: frozenset(),
    SessionState.CANCELLED: frozenset(),
}


class SessionError(Exception):
    """Base for every refusal this module issues.

    Carries a stable ``reason`` so an API layer can map it to a status code
    without matching on prose, and so a client can act on it.
    """

    reason = "session_error"
    status = 409

    def __init__(
        self,
        message: str,
        *,
        reason: Optional[str] = None,
        status: Optional[int] = None,
        **detail: Any,
    ):
        super().__init__(message)
        self.message = message
        self.detail = detail
        # Named explicitly rather than swept into ``detail``: passing
        # ``reason=`` and having it land in the payload while ``exc.reason``
        # kept saying "session_error" is exactly the kind of near-miss that
        # makes a client's error handling silently wrong.
        if reason:
            self.reason = reason
        if status:
            self.status = status

    def as_dict(self) -> dict:
        return {"error": self.message, "reason": self.reason, **self.detail}


class InvalidTransition(SessionError):
    reason = "invalid_transition"


class NotApproved(SessionError):
    """A build was asked for without an approval that covers it."""

    reason = "approval_required"
    status = 403


class AlreadyBuilt(SessionError):
    """This exact revision has already been built."""

    reason = "already_built"
    status = 409


class BlueprintDrifted(SessionError):
    """What is about to be built is not what was approved."""

    reason = "blueprint_drifted"
    status = 409


def can_transition(current: SessionState, target: SessionState) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def transition(current: SessionState, target: SessionState) -> SessionState:
    """``target`` if the move is legal, else raise.

    Returns the new state rather than mutating anything, so the caller decides
    when it becomes true and a refused move cannot leave a half-applied change.
    """
    if not can_transition(current, target):
        raise InvalidTransition(
            f"a session in {current.value} cannot move to {target.value}",
            current=current.value,
            target=target.value,
            allowed=sorted(s.value for s in TRANSITIONS.get(current, frozenset())),
        )
    return target


def authorize_build(
    state: SessionState,
    approval: ApprovalState,
    build_status: BuildStatus,
    approved_hash: Optional[str],
    blueprint_hash: Optional[str],
    force: bool = False,
) -> None:
    """Raise unless this revision may be built right now. Returns None if it may.

    Four conditions, each of which has to hold on its own:

    1. the session is in ``approved`` — not merely "was approved once";
    2. the revision itself carries an approval, so approving revision 2 does not
       authorise building revision 3;
    3. the revision has not already been built, which is what makes a repeated
       request idempotent instead of a second charge for the same geometry;
    4. the hash recorded at approval still matches the Blueprint on the
       revision. A plan that changed after a person said yes has not been
       approved, whatever the state column says.

    ``force`` waives only the already-built condition — a deliberate rebuild of
    an approved design is legitimate. It never waives the approval or the hash.
    """
    if state is not SessionState.APPROVED:
        raise NotApproved(
            "this design has not been approved for building",
            state=state.value,
        )
    if approval is not ApprovalState.APPROVED:
        raise NotApproved(
            "this revision has not been approved",
            approval=approval.value,
        )
    if build_status is BuildStatus.BUILT and not force:
        raise AlreadyBuilt(
            "this revision has already been built",
            build_status=build_status.value,
        )
    if not approved_hash or not blueprint_hash:
        raise BlueprintDrifted(
            "this revision has no frozen Blueprint to build",
            approved_hash=approved_hash or "",
            blueprint_hash=blueprint_hash or "",
        )
    if approved_hash != blueprint_hash:
        raise BlueprintDrifted(
            "the Blueprint changed after it was approved, so the approval no "
            "longer covers it",
            approved_hash=approved_hash[:12],
            blueprint_hash=blueprint_hash[:12],
        )


#: Variables whose change alters what the part *is*, rather than tuning it.
#: Kept deliberately small: over-classifying sends every repair back to a human
#: and the approval stops meaning anything.
def needs_reapproval(
    before: dict, after: dict, tol_rel: float = 0.05
) -> tuple[bool, list[str]]:
    """Whether a revision changed enough that the earlier approval is void.

    A repair that moves a dimension by a fraction of a percent to satisfy a
    guard is the system doing its job, and interrupting a person for it trains
    them to approve without reading. A repair that adds a variable, drops one,
    or moves one by more than ``tol_rel`` has changed the design, and the person
    who approved the old one did not approve this.

    Returns ``(needed, reasons)`` — the reasons are shown, because "this needs
    your approval again" without saying what moved is a dialog people click
    through.
    """
    reasons: list[str] = []

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    if added:
        reasons.append("new dimensions: " + ", ".join(added))
    if removed:
        reasons.append("dimensions removed: " + ", ".join(removed))

    for name in sorted(set(before) & set(after)):
        old, new = before[name], after[name]
        try:
            old_f, new_f = float(old), float(new)
        except (TypeError, ValueError):
            if old != new:
                reasons.append(f"{name} changed from {old!r} to {new!r}")
            continue
        if old_f == new_f:
            continue
        scale = max(abs(old_f), abs(new_f), 1e-12)
        if abs(new_f - old_f) / scale > tol_rel:
            reasons.append(f"{name} {old_f:g} → {new_f:g}")

    return bool(reasons), reasons
