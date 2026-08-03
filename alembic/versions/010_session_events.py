"""session_events + design_revisions.build_call_id: a build that outlives its request

Until now a build was the request: the connection stayed open for the two or
three minutes FreeCAD took, and if it did not, the result was lost. That is
already awkward, and with an approval in the middle it stops working entirely —
a person reading a plan is not going to do it inside a socket timeout, and on a
scale-to-zero host the container that started the build is often gone before it
finishes.

``build_call_id`` is the fix for the second half: the builder's own handle, which
any container can resolve. The build result belongs to the builder until someone
collects it, so nothing is lost when the API scales to zero mid-build.

``session_events`` is the fix for the first: progress becomes an append-only log
with a per-session sequence number rather than a stream held open on one
connection. A client reconnecting sends the last ``seq`` it saw and gets
everything after it.

The unique constraint on (session_id, seq) is load-bearing rather than tidy. Two
writers racing to append would otherwise both compute the same next number and
both succeed, and a cursor would then skip one of them permanently — a silently
missing event being much worse than a collision that can be retried.

Revision ID: 010
Revises: 009
Create Date: 2026-08-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "design_revisions",
        sa.Column("build_call_id", sa.String(120), nullable=True),
    )

    op.create_table(
        "session_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_event_seq"),
    )
    op.create_index("ix_session_events_session_id", "session_events", ["session_id"])
    op.create_index(
        "ix_session_events_session_seq", "session_events", ["session_id", "seq"]
    )
    op.execute("ALTER TABLE session_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("session_events")
    op.drop_column("design_revisions", "build_call_id")
