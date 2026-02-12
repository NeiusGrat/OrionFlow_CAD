"""
SQLAlchemy ORM models for OrionFlow.

Models:
- User: User accounts and authentication
- Design: CAD designs owned by users
- GenerationHistory: History of CAD generations
- APIKey: API keys for programmatic access
- AuditLog: Audit trail of user actions
- PricingPlan: Subscription plans
- Subscription: User subscriptions
- UsageRecord: Usage tracking for billing
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Enum as SQLEnum,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
import enum


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# =============================================================================
# Enums
# =============================================================================

class UserRole(str, enum.Enum):
    """User roles for RBAC."""
    USER = "user"
    ADMIN = "admin"
    DEVELOPER = "developer"


class UserStatus(str, enum.Enum):
    """User account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class SubscriptionStatus(str, enum.Enum):
    """Subscription status."""
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"


class GenerationStatus(str, enum.Enum):
    """CAD generation status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditAction(str, enum.Enum):
    """Audit log action types."""
    LOGIN = "login"
    LOGOUT = "logout"
    SIGNUP = "signup"
    PASSWORD_CHANGE = "password_change"
    DESIGN_CREATE = "design_create"
    DESIGN_UPDATE = "design_update"
    DESIGN_DELETE = "design_delete"
    GENERATION_START = "generation_start"
    GENERATION_COMPLETE = "generation_complete"
    SUBSCRIPTION_CREATE = "subscription_create"
    SUBSCRIPTION_CANCEL = "subscription_cancel"
    API_KEY_CREATE = "api_key_create"
    API_KEY_REVOKE = "api_key_revoke"


# =============================================================================
# User Model
# =============================================================================

class User(Base):
    """
    User account model.

    Stores authentication credentials, profile info, and settings.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Account status
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole),
        default=UserRole.USER,
        nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus),
        default=UserStatus.PENDING_VERIFICATION,
        nullable=False
    )
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String(255))

    # Profile
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    company: Mapped[Optional[str]] = mapped_column(String(255))

    # Settings (JSON for flexibility)
    settings: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Password reset
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255))
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    designs: Mapped[List["Design"]] = relationship(
        "Design", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["APIKey"]] = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan"
    )
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="user", uselist=False
    )
    usage_records: Mapped[List["UsageRecord"]] = relationship(
        "UsageRecord", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_email_status", "email", "status"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# =============================================================================
# Design Model
# =============================================================================

class Design(Base):
    """
    CAD design model.

    Stores design metadata and feature graphs.
    """
    __tablename__ = "designs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Design metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Feature graph (the actual CAD data)
    feature_graph: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # File paths (S3 keys in production)
    glb_path: Mapped[Optional[str]] = mapped_column(String(500))
    step_path: Mapped[Optional[str]] = mapped_column(String(500))
    stl_path: Mapped[Optional[str]] = mapped_column(String(500))
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Metadata
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="designs")
    generation_history: Mapped[List["GenerationHistory"]] = relationship(
        "GenerationHistory", back_populates="design", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_designs_user_created", "user_id", "created_at"),
        Index("ix_designs_public", "is_public", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Design {self.name}>"


# =============================================================================
# Generation History Model
# =============================================================================

class GenerationHistory(Base):
    """
    History of CAD generation attempts.

    Tracks each generation request for analytics and debugging.
    """
    __tablename__ = "generation_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("designs.id", ondelete="SET NULL"),
        index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Request data
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    feature_graph: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    # Response data
    status: Mapped[GenerationStatus] = mapped_column(
        SQLEnum(GenerationStatus),
        default=GenerationStatus.PENDING
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(String(50))

    # Metrics
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    llm_tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Execution trace for debugging
    execution_trace: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    design: Mapped[Optional["Design"]] = relationship(
        "Design", back_populates="generation_history"
    )

    __table_args__ = (
        Index("ix_generation_history_user_status", "user_id", "status"),
        Index("ix_generation_history_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<GenerationHistory {self.id} status={self.status}>"


# =============================================================================
# API Key Model
# =============================================================================

class APIKey(Base):
    """
    API key for programmatic access.

    Supports key rotation and usage tracking.
    """
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Key data (store hash, not plaintext)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False)  # First 8 chars for identification
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # Permissions (JSON array of scopes)
    scopes: Mapped[List[str]] = mapped_column(JSONB, default=list)

    # Rate limiting
    rate_limit: Mapped[int] = mapped_column(Integer, default=1000)  # requests per hour

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Usage tracking
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_user_active", "user_id", "is_active"),
        Index("ix_api_keys_prefix", "key_prefix"),
    )

    def __repr__(self) -> str:
        return f"<APIKey {self.key_prefix}... for user {self.user_id}>"


# =============================================================================
# Audit Log Model
# =============================================================================

class AuditLog(Base):
    """
    Audit trail for security and compliance.

    Tracks all significant user actions.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True
    )

    # Action details
    action: Mapped[AuditAction] = mapped_column(SQLEnum(AuditAction), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(255))

    # Request context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))  # IPv6 max length
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    request_id: Mapped[Optional[str]] = mapped_column(String(36))

    # Additional details (JSON for flexibility)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    # Status
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_user_action", "user_id", "action"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} by {self.user_id}>"


# =============================================================================
# Pricing Plan Model
# =============================================================================

class PricingPlan(Base):
    """
    Subscription pricing plans.

    Defines available plans and their limits.
    """
    __tablename__ = "pricing_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    # Plan details
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Pricing (in cents to avoid float issues)
    price_monthly_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    price_yearly_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Stripe integration
    stripe_price_id_monthly: Mapped[Optional[str]] = mapped_column(String(100))
    stripe_price_id_yearly: Mapped[Optional[str]] = mapped_column(String(100))

    # Limits
    generations_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    max_designs: Mapped[int] = mapped_column(Integer, nullable=False)
    max_file_size_mb: Mapped[int] = mapped_column(Integer, default=50)

    # Features (JSON for flexibility)
    features: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="plan"
    )

    def __repr__(self) -> str:
        return f"<PricingPlan {self.name}>"


# =============================================================================
# Subscription Model
# =============================================================================

class Subscription(Base):
    """
    User subscription to a pricing plan.

    Tracks billing cycle and usage limits.
    """
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pricing_plans.id"),
        nullable=False
    )

    # Stripe integration
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(100))
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Status
    status: Mapped[SubscriptionStatus] = mapped_column(
        SQLEnum(SubscriptionStatus),
        default=SubscriptionStatus.TRIALING
    )

    # Billing cycle
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Usage tracking (reset each billing period)
    generations_used: Mapped[int] = mapped_column(Integer, default=0)

    # Cancellation
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Trial
    trial_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscription")
    plan: Mapped["PricingPlan"] = relationship("PricingPlan", back_populates="subscriptions")

    __table_args__ = (
        Index("ix_subscriptions_status", "status"),
        Index("ix_subscriptions_stripe", "stripe_subscription_id"),
    )

    def __repr__(self) -> str:
        return f"<Subscription {self.user_id} plan={self.plan_id}>"


# =============================================================================
# Usage Record Model
# =============================================================================

class UsageRecord(Base):
    """
    Detailed usage tracking for metered billing.

    Tracks each generation for usage-based billing.
    """
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Usage details
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # Billing
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    reported_to_stripe: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_usage_record_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Extra data
    extra_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="usage_records")

    __table_args__ = (
        Index("ix_usage_records_user_action", "user_id", "action", "created_at"),
        Index("ix_usage_records_unreported", "reported_to_stripe", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<UsageRecord {self.action} by {self.user_id}>"
