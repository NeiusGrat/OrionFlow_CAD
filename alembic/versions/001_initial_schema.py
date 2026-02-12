"""Initial database schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial database schema."""

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('user', 'admin', 'developer', name='userrole'), nullable=False, default='user'),
        sa.Column('status', sa.Enum('active', 'inactive', 'suspended', 'pending_verification', name='userstatus'), nullable=False, default='pending_verification'),
        sa.Column('email_verified', sa.Boolean, default=False),
        sa.Column('email_verification_token', sa.String(255)),
        sa.Column('avatar_url', sa.String(500)),
        sa.Column('company', sa.String(255)),
        sa.Column('settings', postgresql.JSONB, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('updated_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('last_login_at', sa.DateTime(timezone=True)),
        sa.Column('password_reset_token', sa.String(255)),
        sa.Column('password_reset_expires', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_users_email_status', 'users', ['email', 'status'])

    # Create pricing_plans table
    op.create_table(
        'pricing_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('price_monthly_cents', sa.Integer, nullable=False),
        sa.Column('price_yearly_cents', sa.Integer, nullable=False),
        sa.Column('stripe_price_id_monthly', sa.String(100)),
        sa.Column('stripe_price_id_yearly', sa.String(100)),
        sa.Column('generations_per_month', sa.Integer, nullable=False),
        sa.Column('max_designs', sa.Integer, nullable=False),
        sa.Column('max_file_size_mb', sa.Integer, default=50),
        sa.Column('features', postgresql.JSONB, default={}),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_public', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    )

    # Create subscriptions table
    op.create_table(
        'subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('pricing_plans.id'), nullable=False),
        sa.Column('stripe_customer_id', sa.String(100)),
        sa.Column('stripe_subscription_id', sa.String(100)),
        sa.Column('status', sa.Enum('active', 'paused', 'cancelled', 'past_due', 'trialing', name='subscriptionstatus'), default='trialing'),
        sa.Column('current_period_start', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('current_period_end', sa.DateTime(timezone=True)),
        sa.Column('generations_used', sa.Integer, default=0),
        sa.Column('cancel_at_period_end', sa.Boolean, default=False),
        sa.Column('cancelled_at', sa.DateTime(timezone=True)),
        sa.Column('trial_end', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('updated_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    )
    op.create_index('ix_subscriptions_status', 'subscriptions', ['status'])
    op.create_index('ix_subscriptions_stripe', 'subscriptions', ['stripe_subscription_id'])

    # Create designs table
    op.create_table(
        'designs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('original_prompt', sa.Text, nullable=False),
        sa.Column('feature_graph', postgresql.JSONB, nullable=False),
        sa.Column('glb_path', sa.String(500)),
        sa.Column('step_path', sa.String(500)),
        sa.Column('stl_path', sa.String(500)),
        sa.Column('thumbnail_path', sa.String(500)),
        sa.Column('is_public', sa.Boolean, default=False),
        sa.Column('tags', postgresql.JSONB, default=[]),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('updated_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    )
    op.create_index('ix_designs_user_created', 'designs', ['user_id', 'created_at'])
    op.create_index('ix_designs_public', 'designs', ['is_public', 'created_at'])

    # Create generation_history table
    op.create_table(
        'generation_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('design_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('designs.id', ondelete='SET NULL'), index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('prompt', sa.Text, nullable=False),
        sa.Column('feature_graph', postgresql.JSONB),
        sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='generationstatus'), default='pending'),
        sa.Column('error_message', sa.Text),
        sa.Column('error_code', sa.String(50)),
        sa.Column('duration_ms', sa.Integer),
        sa.Column('llm_tokens_used', sa.Integer),
        sa.Column('retry_count', sa.Integer, default=0),
        sa.Column('execution_trace', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_generation_history_user_status', 'generation_history', ['user_id', 'status'])
    op.create_index('ix_generation_history_created', 'generation_history', ['created_at'])

    # Create api_keys table
    op.create_table(
        'api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key_prefix', sa.String(10), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False, unique=True),
        sa.Column('scopes', postgresql.JSONB, default=[]),
        sa.Column('rate_limit', sa.Integer, default=1000),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True)),
        sa.Column('usage_count', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_api_keys_user_active', 'api_keys', ['user_id', 'is_active'])
    op.create_index('ix_api_keys_prefix', 'api_keys', ['key_prefix'])

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), index=True),
        sa.Column('action', sa.Enum('login', 'logout', 'signup', 'password_change', 'design_create', 'design_update', 'design_delete', 'generation_start', 'generation_complete', 'subscription_create', 'subscription_cancel', 'api_key_create', 'api_key_revoke', name='auditaction'), nullable=False),
        sa.Column('resource_type', sa.String(50)),
        sa.Column('resource_id', sa.String(255)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.String(500)),
        sa.Column('request_id', sa.String(36)),
        sa.Column('details', postgresql.JSONB),
        sa.Column('success', sa.Boolean, default=True),
        sa.Column('error_message', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True),
    )
    op.create_index('ix_audit_logs_user_action', 'audit_logs', ['user_id', 'action'])
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])

    # Create usage_records table
    op.create_table(
        'usage_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('quantity', sa.Integer, default=1),
        sa.Column('billable', sa.Boolean, default=True),
        sa.Column('reported_to_stripe', sa.Boolean, default=False),
        sa.Column('stripe_usage_record_id', sa.String(100)),
        sa.Column('metadata', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True),
    )
    op.create_index('ix_usage_records_user_action', 'usage_records', ['user_id', 'action', 'created_at'])
    op.create_index('ix_usage_records_unreported', 'usage_records', ['reported_to_stripe', 'created_at'])

    # Insert default pricing plans
    op.execute("""
        INSERT INTO pricing_plans (id, name, display_name, description, price_monthly_cents, price_yearly_cents, generations_per_month, max_designs, features) VALUES
        (gen_random_uuid(), 'free', 'Free', 'Get started with OrionFlow', 0, 0, 10, 5, '{"exports": ["glb"], "support": "community"}'),
        (gen_random_uuid(), 'pro', 'Pro', 'For individuals and small teams', 1999, 19990, 100, 50, '{"exports": ["glb", "step", "stl"], "support": "email", "api_access": true}'),
        (gen_random_uuid(), 'enterprise', 'Enterprise', 'For large organizations', 9999, 99990, 1000, 500, '{"exports": ["glb", "step", "stl", "iges"], "support": "priority", "api_access": true, "sso": true, "audit_logs": true}')
    """)


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('usage_records')
    op.drop_table('audit_logs')
    op.drop_table('api_keys')
    op.drop_table('generation_history')
    op.drop_table('designs')
    op.drop_table('subscriptions')
    op.drop_table('pricing_plans')
    op.drop_table('users')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS userrole')
    op.execute('DROP TYPE IF EXISTS userstatus')
    op.execute('DROP TYPE IF EXISTS subscriptionstatus')
    op.execute('DROP TYPE IF EXISTS generationstatus')
    op.execute('DROP TYPE IF EXISTS auditaction')
