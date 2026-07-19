"""Repair-trace column on ofl_events

Each self-repair attempt's (failed code, error) is persisted so that, with
the final ofl_code, every repaired generation yields training triples for
teaching a model to converge inside the harness.

Revision ID: 004
Revises: 003
Create Date: 2026-07-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ofl_events",
        sa.Column("repair_trace", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ofl_events", "repair_trace")
