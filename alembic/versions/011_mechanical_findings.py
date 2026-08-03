"""design_revisions.mechanical: the engineering review that runs before FreeCAD

Between a frozen Blueprint and the kernel there was nothing. ``resolve()``
substituted expressions into a graph and handed it over, so any engineering
judgement the model did not happen to have was simply absent — and the first
thing to notice was either OCC three seconds later, or nobody.

``app/services/mechanical_plan.py`` fills that gap: it reads the resolved graph,
where every dimension is a number and every sketch is line segments and circles
with real coordinates, and reports what arithmetic can settle. Holes that
overlap. Dimensions that resolve non-positive. A fillet larger than the face it
is applied to.

Stored in its own column rather than folded into ``critique`` because the two
answer different questions. ``critique`` grades the model against the contract
it wrote for itself — its own preconditions, its own closed-form volume.
``mechanical`` grades the part against mechanics, which the model was never
asked to state. A corpus that cannot tell them apart cannot learn from either.

Revision ID: 011
Revises: 010
Create Date: 2026-08-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "design_revisions",
        sa.Column("mechanical", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("design_revisions", "mechanical")
