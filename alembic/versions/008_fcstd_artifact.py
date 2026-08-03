"""fcstd_path on designs: keep the parametric document, not only the solid

Every build has always written a part.FCStd — ``orion/build_export_fc.py`` saves
the document before it exports anything — but nothing downstream carried it. The
Modal builder returned only part.step and part.stl, so on the cloud path the
FCStd died with the container, and there was nowhere on ``designs`` to record it
even when it survived locally.

That made every saved design a dead shape. STEP and STL are the finished solid;
the FCStd is the feature history, the sketches and the expressions that bind
each dimension to a named variable — the difference between a part you can
reopen and retune and a part you can only look at.

Nullable with no backfill, deliberately: designs saved before this migration
have no FCStd to point at. It was not lost in transit, it was never kept.

Revision ID: 008
Revises: 007
Create Date: 2026-08-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "designs",
        sa.Column("fcstd_path", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("designs", "fcstd_path")
