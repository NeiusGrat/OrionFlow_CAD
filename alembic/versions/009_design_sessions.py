"""design_sessions + design_revisions: the design between the prompt and the part

``designs`` records what a user chose to keep and ``generation_history`` records
what the kernel did. Neither records the middle — the plan that was proposed,
the person who approved or rejected it, and the revision that replaced it. Until
now there was no such thing as "the design, before it was built", so there was
nowhere to put an approval and nothing to replay.

Two tables, append-only by convention:

``design_sessions``
    one row per design, carrying the state it is resting in. The transition
    table that governs it is in app/domain/design_session.py, not in a check
    constraint — the rules are richer than a column can express, and a rule
    split across both is a rule that will disagree with itself.

``design_revisions``
    one row per frozen Blueprint. Never updated in place except to record a
    decision or a build result; a change makes the next revision with
    ``parent_number`` pointing back. Rejected revisions stay, with their
    critique and their rejection note attached — a design a human judged wrong
    is a better record than the one that survived, and the note is the only
    thing here no synthetic pipeline can produce.

``uq_design_revision_number`` is the idempotency spine: a retried proposal
collides on (session_id, number) rather than silently forking the history.

Revision ID: 009
Revises: 008
Create Date: 2026-08-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SESSION_STATE = (
    "draft",
    "questions",
    "awaiting_approval",
    "approved",
    "building",
    "built",
    "needs_revision",
    "completed",
    "rejected",
    "cancelled",
    "failed",
)
APPROVAL_STATE = ("pending", "approved", "rejected", "superseded")
BUILD_STATUS = ("not_built", "building", "built", "failed")
REVISION_ORIGIN = ("model", "repair", "revision", "retune")


def upgrade() -> None:
    # create_type=False on the column definitions below, so the enum types are
    # created exactly once here rather than twice by two columns referencing
    # them.
    session_state = postgresql.ENUM(*SESSION_STATE, name="sessionstate")
    approval_state = postgresql.ENUM(*APPROVAL_STATE, name="approvalstate")
    build_status = postgresql.ENUM(*BUILD_STATUS, name="buildstatus")
    revision_origin = postgresql.ENUM(*REVISION_ORIGIN, name="revisionorigin")
    bind = op.get_bind()
    for t in (session_state, approval_state, build_status, revision_origin):
        t.create(bind, checkfirst=True)

    op.create_table(
        "design_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_prompt", sa.Text(), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(*SESSION_STATE, name="sessionstate", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("part_class", sa.String(120), nullable=True),
        sa.Column("open_questions", postgresql.JSONB(), nullable=True),
        sa.Column("reasoning", postgresql.JSONB(), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("provider", sa.String(60), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_design_sessions_user_id", "design_sessions", ["user_id"])
    op.create_index(
        "ix_design_sessions_user_created", "design_sessions", ["user_id", "created_at"]
    )
    op.create_index("ix_design_sessions_state", "design_sessions", ["state"])

    op.create_table(
        "design_revisions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("parent_number", sa.Integer(), nullable=True),
        sa.Column(
            "origin",
            postgresql.ENUM(*REVISION_ORIGIN, name="revisionorigin", create_type=False),
            nullable=False,
            server_default="model",
        ),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column("blueprint", postgresql.JSONB(), nullable=True),
        sa.Column("blueprint_hash", sa.String(64), nullable=True),
        sa.Column("part_class", sa.String(120), nullable=True),
        sa.Column("variables", postgresql.JSONB(), nullable=True),
        sa.Column("design_plan", postgresql.JSONB(), nullable=True),
        sa.Column("assertions", postgresql.JSONB(), nullable=True),
        sa.Column("critique", postgresql.JSONB(), nullable=True),
        sa.Column("thinking", sa.Text(), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column(
            "approval",
            postgresql.ENUM(*APPROVAL_STATE, name="approvalstate", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "build_status",
            postgresql.ENUM(*BUILD_STATUS, name="buildstatus", create_type=False),
            nullable=False,
            server_default="not_built",
        ),
        sa.Column("request_id", sa.String(32), nullable=True),
        sa.Column("build_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification", postgresql.JSONB(), nullable=True),
        sa.Column("stats", postgresql.JSONB(), nullable=True),
        sa.Column("artifacts", postgresql.JSONB(), nullable=True),
        sa.Column("freecad_version", sa.String(40), nullable=True),
        sa.Column("build_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("session_id", "number", name="uq_design_revision_number"),
    )
    op.create_index("ix_design_revisions_session_id", "design_revisions", ["session_id"])
    op.create_index(
        "ix_design_revisions_session_number", "design_revisions", ["session_id", "number"]
    )
    op.create_index(
        "ix_design_revisions_blueprint_hash", "design_revisions", ["blueprint_hash"]
    )
    op.create_index("ix_design_revisions_request_id", "design_revisions", ["request_id"])

    # Same posture as migration 005: the backend connects as the owner and no
    # supabase-js client reaches these tables, but RLS stays on so a future
    # anon key cannot read another user's design history.
    op.execute("ALTER TABLE design_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE design_revisions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("design_revisions")
    op.drop_table("design_sessions")
    bind = op.get_bind()
    for name in ("revisionorigin", "buildstatus", "approvalstate", "sessionstate"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
