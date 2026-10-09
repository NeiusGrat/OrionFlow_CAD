"""demo_requests: "Book a demo" submissions from the landing page

The demo button used to open a calendar embed and nothing else, so a visitor
who closed it without booking left no trace. The form now asks who they are
and what they want to see first, and that is stored here before the calendar
is offered.

RLS is enabled with no policies, as migration 005 does for every other public
table: the backend connects as the owner, and Supabase's anon/authenticated
roles see nothing.

Revision ID: 014
Revises: 013
Create Date: 2026-10-09 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_demo_requests_created", "demo_requests", ["created_at"])
    op.create_index("ix_demo_requests_email", "demo_requests", ["email"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.demo_requests ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_demo_requests_email", table_name="demo_requests")
    op.drop_index("ix_demo_requests_created", table_name="demo_requests")
    op.drop_table("demo_requests")
