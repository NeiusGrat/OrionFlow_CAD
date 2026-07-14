"""OFL pipeline telemetry table

Revision ID: 002
Revises: 001
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ofl_events telemetry table."""
    op.create_table(
        'ofl_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('event_type', sa.String(16), nullable=False),
        sa.Column('prompt', sa.Text),
        sa.Column('input_code', sa.Text),
        sa.Column('ofl_code', sa.Text),
        sa.Column('success', sa.Boolean, nullable=False),
        sa.Column('error', sa.Text),
        sa.Column('repair_attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('generation_time_ms', sa.Integer),
        sa.Column('watertight', sa.Boolean),
        sa.Column('volume_mm3', sa.Float),
        sa.Column('bbox_mm', postgresql.JSONB),
        sa.Column('triangles', sa.Integer),
    )
    op.create_index('ix_ofl_events_user_id', 'ofl_events', ['user_id'])
    op.create_index('ix_ofl_events_created', 'ofl_events', ['created_at'])
    op.create_index('ix_ofl_events_type_success', 'ofl_events', ['event_type', 'success'])


def downgrade() -> None:
    """Drop the ofl_events table."""
    op.drop_index('ix_ofl_events_type_success', table_name='ofl_events')
    op.drop_index('ix_ofl_events_created', table_name='ofl_events')
    op.drop_index('ix_ofl_events_user_id', table_name='ofl_events')
    op.drop_table('ofl_events')
