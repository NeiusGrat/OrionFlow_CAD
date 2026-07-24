"""Enable Row Level Security on all public tables

Supabase exposes every table in the ``public`` schema through PostgREST, and
its default grants let the ``anon`` / ``authenticated`` roles reach them with
just the project's public anon key. With RLS off that means anyone with the
project URL can read/write these tables directly — the Security Advisor flags
this as ``rls_disabled_in_public`` (11 errors, one per table below).

This app never uses PostgREST/anon: it talks to Postgres only through the
FastAPI backend, which connects as the table owner (Supabase ``postgres`` /
service role) and therefore *bypasses* RLS. Enabling RLS with no policies is
default-deny for anon/authenticated while leaving the backend untouched, so it
closes the hole without any application change.

``alembic_version`` is included: it is Alembic's own bookkeeping table, is not
application data, and should never be reachable via the API. The owner still
stamps it after each migration because owners bypass RLS.

Revision ID: 005
Revises: 004
Create Date: 2026-07-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every table living in the public schema, including Alembic's own version
# table. IF EXISTS keeps the migration portable across environments where a
# table may not have been created yet.
_PUBLIC_TABLES = (
    "users",
    "pricing_plans",
    "subscriptions",
    "designs",
    "generation_history",
    "api_keys",
    "audit_logs",
    "usage_records",
    "ofl_events",
    "waitlist_entries",
    "alembic_version",
)


def upgrade() -> None:
    """Turn RLS on for every public table (default-deny for anon)."""
    for table in _PUBLIC_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Turn RLS back off."""
    for table in _PUBLIC_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS public.{table} DISABLE ROW LEVEL SECURITY")
