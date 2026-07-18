"""Early-access waitlist table

Revision ID: 003
Revises: 002
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the waitlist_entries table."""
    op.create_table(
        'waitlist_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(320), nullable=False, unique=True),
        sa.Column('source', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_waitlist_entries_created', 'waitlist_entries', ['created_at'])


def downgrade() -> None:
    """Drop the waitlist_entries table."""
    op.drop_index('ix_waitlist_entries_created', table_name='waitlist_entries')
    op.drop_table('waitlist_entries')
