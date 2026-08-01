"""Seed the Free and Pro plans

Until now ``pricing_plans`` was empty, which had a quieter consequence than it
sounds: ``check_usage_limit`` joins a subscription to a plan, finds nothing for
anybody, and falls through to the free-tier branch for every user. Metering
worked, but "Pro" did not exist as a thing the database could describe, and
``GET /api/v1/billing/plans`` — which the pricing page reads — returned an empty
list.

Reference data, so it belongs in a migration rather than a script somebody has
to remember to run; ``alembic upgrade head`` already runs at container boot.

Two deliberate omissions:

* **No Stripe price ids.** The products do not exist in Stripe yet. Checkout
  reads ``stripe_price_id_monthly`` and will refuse until they are created and
  filled in; that is the correct failure — better than a checkout that appears
  to work.
* **No subscription rows for free users.** Free users stay subscription-less and
  are counted against ``settings.free_tier_generations``, which is how
  ``check_usage_limit`` already behaves. The Free plan row exists so the pricing
  page can display it, not to be subscribed to.

Idempotent by name, so re-running against a database that already has the rows
is a no-op rather than a duplicate-key error.

Revision ID: 007
Revises: 006
Create Date: 2026-08-01 00:00:00.000000

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Yearly is priced at ten months, the usual two-months-free convention. It is a
#: commercial choice rather than a technical one and is trivial to change here.
PLANS = [
    {
        "name": "free",
        "display_name": "Free",
        "description": "Design and verify parts, with a monthly allowance.",
        "price_monthly_cents": 0,
        "price_yearly_cents": 0,
        # Matches settings.free_tier_generations / free_tier_max_designs, which
        # is what actually governs a subscription-less user. Divergence here
        # would show the user one number and enforce another.
        "generations_per_month": 10,
        "max_designs": 5,
        "features": {
            "verified_builds": True,
            "step_stl_glb_export": True,
            "share_projects": False,
            "support": "community",
        },
    },
    {
        "name": "pro",
        "display_name": "Pro",
        "description": "For engineers designing every day.",
        "price_monthly_cents": 5000,
        "price_yearly_cents": 50000,
        "generations_per_month": 100,
        "max_designs": 1000,
        "features": {
            "verified_builds": True,
            "step_stl_glb_export": True,
            "share_projects": True,
            "support": "priority",
        },
    },
]


def upgrade() -> None:
    plans = sa.table(
        "pricing_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("price_monthly_cents", sa.Integer),
        sa.column("price_yearly_cents", sa.Integer),
        sa.column("generations_per_month", sa.Integer),
        sa.column("max_designs", sa.Integer),
        sa.column("max_file_size_mb", sa.Integer),
        sa.column("features", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
        sa.column("is_public", sa.Boolean),
    )

    connection = op.get_bind()
    existing = {
        row[0]
        for row in connection.execute(sa.text("SELECT name FROM pricing_plans"))
    }

    rows = [
        {
            "id": uuid.uuid4(),
            "max_file_size_mb": 50,
            "is_active": True,
            "is_public": True,
            **plan,
        }
        for plan in PLANS
        if plan["name"] not in existing
    ]
    if rows:
        op.bulk_insert(plans, rows)


def downgrade() -> None:
    """Remove the seeded plans, but never a plan somebody is on.

    ``subscriptions.plan_id`` references these rows with no ON DELETE clause, so
    a blanket delete raises a foreign-key violation the moment one paying user
    exists — the downgrade fails halfway and the migration state is left
    ambiguous. Deleting only unreferenced rows makes the downgrade succeed and
    leaves the evidence: a 'pro' row that survives is a row with subscribers,
    which is exactly the thing an operator needs to know about before rolling
    this back any further.
    """
    op.execute(sa.text("""
        DELETE FROM pricing_plans
        WHERE name IN ('free', 'pro')
          AND id NOT IN (SELECT plan_id FROM subscriptions)
    """))
