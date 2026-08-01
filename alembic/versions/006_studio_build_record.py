"""request_id on generation_history: link a build to the design saved from it

Every studio build now writes a generation_history row carrying the per-feature
evidence the kernel produced — addsub volumes, recompute errors, the assertion
rows. That evidence was previously computed and thrown away when the request
ended, which is why a saved design could show what it *is* but never how it was
built or which feature failed.

The link has to be the build's own request_id rather than the design id, because
the two are created at different times: the build happens first and the user may
never save it. Indexed and unique-per-user by query, not by constraint — a
retried write with the same request_id should update the link, not fail the
request.

Revision ID: 006
Revises: 005
Create Date: 2026-08-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_history",
        sa.Column("request_id", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_generation_history_request_id",
        "generation_history",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_history_request_id",
                  table_name="generation_history")
    op.drop_column("generation_history", "request_id")
