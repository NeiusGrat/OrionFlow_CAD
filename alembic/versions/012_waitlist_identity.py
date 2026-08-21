"""waitlist_entries.name / .company: who is actually trying the product

The landing page collected an email and nothing else, which answers "how many"
and no other question. "Try OrionFlow" now opens a three-field intake — name,
company, work email — before the studio, because the point of early access is
to know who is testing it and be able to follow up.

Both columns are nullable. Every row written before this migration is a real
signup with a real email and no name, and back-filling a placeholder would turn
"we do not know" into a value that reads as one.

The honeypot moved at the same time. `company` used to be the hidden bot trap on
the landing form — any value in it meant a bot and the row was dropped. It is a
real field now, so the trap moved to `website`, which is never stored under any
circumstances.

Revision ID: 012
Revises: 011
Create Date: 2026-08-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "waitlist_entries", sa.Column("name", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "waitlist_entries", sa.Column("company", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("waitlist_entries", "company")
    op.drop_column("waitlist_entries", "name")
