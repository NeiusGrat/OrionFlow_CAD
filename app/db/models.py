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
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
import enum

# The session lifecycle is domain logic, not storage: the transition table and
# the approval gate live in app/domain/design_session.py so they can be tested
# without a database. These columns only persist their result.
from app.domain.design_session import (  # noqa: E402
    ApprovalState,
    BuildStatus,
    RevisionOrigin,
    SessionState,
)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# =============================================================================
# Enums
# =============================================================================


def ValueEnum(enum_cls) -> SQLEnum:
    """SQLEnum that persists member VALUES (e.g. 'signup'), matching the
    lowercase values the migrations created the Postgres enum types with.
    Bare SQLEnum persists member NAMES ('SIGNUP') and fails at insert."""
    return SQLEnum(enum_cls, values_callable=lambda e: [m.value for m in e])


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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Account status
    role: Mapped[UserRole] = mapped_column(
        ValueEnum(UserRole), default=UserRole.USER, nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        ValueEnum(UserStatus), default=UserStatus.PENDING_VERIFICATION, nullable=False
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Password reset
    password_reset_token: Mapped[Optional[str]] = mapped_column(String(255))
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

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

    __table_args__ = (Index("ix_users_email_status", "email", "status"),)

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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    #: The parametric FreeCAD document. Unlike the three above it is not a view
    #: of the finished solid — it holds the sketches, the feature history and
    #: the expressions binding dimensions to named variables, so it is the only
    #: artifact from which this design can be reopened and retuned rather than
    #: merely displayed. Nullable because designs saved before this column
    #: existed genuinely have no FCStd: it was discarded at build time.
    fcstd_path: Mapped[Optional[str]] = mapped_column(String(500))
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Metadata
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("designs.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Request data
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    feature_graph: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    #: The build's own id, handed to the client with the artifacts. A design is
    #: saved (if at all) some time after the build that produced it, so this is
    #: what lets the two be joined afterwards — design_id above is set at that
    #: point, not at build time.
    request_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)

    # Response data
    status: Mapped[GenerationStatus] = mapped_column(
        ValueEnum(GenerationStatus), default=GenerationStatus.PENDING
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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
# Design Sessions — a design that exists before it is a solid
# =============================================================================


class DesignSession(Base):
    """One design, from the prompt to the part someone accepted.

    ``designs`` records what a user chose to keep; ``generation_history``
    records what the kernel did. Neither records the part in between — the plan
    that was proposed, the person who said no to it, and the revision that
    replaced it. That middle is where the engineering actually happens, and it
    was the only part of a studio turn that was never written down.

    The state machine lives in ``app/domain/design_session.py`` and is enforced
    there. This table only stores where a session got to.
    """

    __tablename__ = "design_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[SessionState] = mapped_column(
        ValueEnum(SessionState), default=SessionState.DRAFT, nullable=False
    )

    #: Which revision the session is currently about. A number rather than a
    #: foreign key: revisions are numbered per session and the pair is already
    #: unique, so this avoids a circular FK between the two tables.
    current_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    part_class: Mapped[Optional[str]] = mapped_column(String(120))
    #: What the request did not say. Kept on the session rather than the
    #: revision because they are properties of the ask, not of any one answer.
    open_questions: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list)
    #: How the request was routed and what the chain derived, if it ran.
    reasoning: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    #: Provenance. Which weights answered, so a session can be replayed against
    #: the model that actually produced it rather than whatever is deployed now.
    model: Mapped[Optional[str]] = mapped_column(String(120))
    provider: Mapped[Optional[str]] = mapped_column(String(60))

    error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    #: When a person accepted the finished part. Distinct from ``updated_at``:
    #: this is the only timestamp that means a human was satisfied.
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User")
    revisions: Mapped[List["DesignRevision"]] = relationship(
        "DesignRevision",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="DesignRevision.number",
    )

    __table_args__ = (
        Index("ix_design_sessions_user_created", "user_id", "created_at"),
        Index("ix_design_sessions_state", "state"),
    )

    def __repr__(self) -> str:
        return f"<DesignSession {self.id} state={self.state}>"


class DesignRevision(Base):
    """One frozen Blueprint, its verdict from a person, and what it built.

    Never edited. A change produces the next revision with ``parent_number``
    pointing back, so the history is append-only and a rejected proposal keeps
    its critique, its reason for rejection and its build result. Those records
    are the point: a design a human judged wrong says more about the model than
    the one that survived.
    """

    __tablename__ = "design_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("design_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: 1-based, unique within the session. Also the idempotency key a build is
    #: keyed on, together with the blueprint hash.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_number: Mapped[Optional[int]] = mapped_column(Integer)
    origin: Mapped[RevisionOrigin] = mapped_column(
        ValueEnum(RevisionOrigin), default=RevisionOrigin.MODEL, nullable=False
    )
    #: Why this revision exists, in words — the repair diagnosis, or what the
    #: person asked to change.
    instruction: Mapped[Optional[str]] = mapped_column(Text)

    # ---- the design ---------------------------------------------------- #
    blueprint: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    #: sha256 over everything the model authored, computed by
    #: ``Blueprint.freeze`` before FreeCAD is involved. This is what an approval
    #: binds to and what a build is checked against.
    blueprint_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    part_class: Mapped[Optional[str]] = mapped_column(String(120))
    variables: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)
    design_plan: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)
    assertions: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSONB, default=list
    )
    #: What was known before the kernel ran — preconditions, the closed-form
    #: volume against the profile it was derived from.
    critique: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)
    #: The deterministic engineering review of the resolved geometry — clashing
    #: holes, dimensions that cannot build, dressups larger than the face they
    #: land on. Separate from ``critique`` because they answer different
    #: questions: one grades the model against its own contract, the other
    #: grades the part against mechanics.
    mechanical: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)
    thinking: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(String(120))

    # ---- the human ----------------------------------------------------- #
    approval: Mapped[ApprovalState] = mapped_column(
        ValueEnum(ApprovalState), default=ApprovalState.PENDING, nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Why a person rejected or revised it. The single most valuable field in
    #: this table and the only one no synthetic pipeline can produce.
    decision_note: Mapped[Optional[str]] = mapped_column(Text)

    # ---- the kernel ---------------------------------------------------- #
    build_status: Mapped[BuildStatus] = mapped_column(
        ValueEnum(BuildStatus), default=BuildStatus.NOT_BUILT, nullable=False
    )
    #: The build's own id, which is also where its artifacts are served from
    #: and how ``generation_history`` joins to this revision.
    request_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    #: The builder's handle — a Modal call id in the cloud. This is what lets a
    #: build outlive the request that started it: any container can resolve the
    #: id and collect the result, so a session is never stranded by the one that
    #: happened to kick it off scaling to zero.
    build_call_id: Mapped[Optional[str]] = mapped_column(String(120))
    build_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    verification: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    stats: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    #: Every built file including the FCStd, keyed by kind.
    artifacts: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)
    freecad_version: Mapped[Optional[str]] = mapped_column(String(40))
    build_error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session: Mapped["DesignSession"] = relationship(
        "DesignSession", back_populates="revisions"
    )

    __table_args__ = (
        # The idempotency spine: a session cannot have two revision 3s, so a
        # retried proposal collides rather than forking the history.
        UniqueConstraint("session_id", "number", name="uq_design_revision_number"),
        Index("ix_design_revisions_session_number", "session_id", "number"),
    )

    def __repr__(self) -> str:
        return f"<DesignRevision {self.session_id}#{self.number} {self.approval}>"


class SessionEvent(Base):
    """One thing that happened, in the order it happened.

    A design session outlives the request that started it — an approval is a
    person reading, and a build is a container somewhere else — so progress
    cannot be a stream held open on one connection. It has to be a log that any
    later request can replay from a cursor.

    ``seq`` is per session and monotonic, and it is the cursor: a client
    reconnecting sends the last one it saw and gets everything after it. The
    unique constraint is what makes that promise real — two writers racing to
    append collide rather than quietly producing two events with the same
    number, which would make the cursor skip one of them forever.
    """

    __tablename__ = "session_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("design_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The event name a client switches on. Free text rather than an enum: a new
    #: event should not need a migration, and a client already ignores names it
    #: does not know.
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[Optional[int]] = mapped_column(Integer)
    data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_session_event_seq"),
        Index("ix_session_events_session_seq", "session_id", "seq"),
    )

    def __repr__(self) -> str:
        return f"<SessionEvent {self.session_id}#{self.seq} {self.type}>"


class OFLEvent(Base):
    """
    Telemetry for the OFL text→CAD pipeline: one row per generate/edit/rebuild.

    Doubles as (a) the product health metric source (success rate, repair
    usage, latency) and (b) a growing prompt→code training corpus with
    ground-truth geometry validation attached. Anonymous events are kept:
    user_id is best-effort from the JWT, never required.
    """

    __tablename__ = "ofl_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Request
    event_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # generate|edit|rebuild
    prompt: Mapped[Optional[str]] = mapped_column(Text)  # NL prompt / edit instruction
    input_code: Mapped[Optional[str]] = mapped_column(Text)  # pre-edit/rebuild code

    # Result
    ofl_code: Mapped[Optional[str]] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0)
    generation_time_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # Geometry validation (trimesh; null when execution failed)
    watertight: Mapped[Optional[bool]] = mapped_column(Boolean)
    volume_mm3: Mapped[Optional[float]] = mapped_column(Float)
    bbox_mm: Mapped[Optional[List[float]]] = mapped_column(JSONB)
    triangles: Mapped[Optional[int]] = mapped_column(Integer)
    # Self-repair steps: [{"code": <failed code>, "error": <traceback>}] —
    # with ofl_code as the final fix these are repair-training triples.
    repair_trace: Mapped[Optional[List[dict]]] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_ofl_events_created", "created_at"),
        Index("ix_ofl_events_type_success", "event_type", "success"),
    )

    def __repr__(self) -> str:
        return f"<OFLEvent {self.event_type} success={self.success}>"


# =============================================================================
# Waitlist Model
# =============================================================================


class WaitlistEntry(Base):
    """
    Early-access waitlist signup from the public landing page.

    Insert-only from the public endpoint; email is unique so repeat
    submissions are idempotent and never leak whether an address exists.
    """

    __tablename__ = "waitlist_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(64))  # e.g. "landing"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_waitlist_entries_created", "created_at"),)

    def __repr__(self) -> str:
        return f"<WaitlistEntry {self.email}>"


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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Key data (store hash, not plaintext)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # First 8 chars for identification
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Action details
    action: Mapped[AuditAction] = mapped_column(ValueEnum(AuditAction), nullable=False)
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pricing_plans.id"), nullable=False
    )

    # Stripe integration
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(100))
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Status
    status: Mapped[SubscriptionStatus] = mapped_column(
        ValueEnum(SubscriptionStatus), default=SubscriptionStatus.TRIALING
    )

    # Billing cycle
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscription")
    plan: Mapped["PricingPlan"] = relationship(
        "PricingPlan", back_populates="subscriptions"
    )

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
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Usage details
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # Billing
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    reported_to_stripe: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_usage_record_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Extra data.
    #
    # The column is named ``metadata`` in the database — see migration 001 —
    # but ``metadata`` cannot be an attribute on a declarative class, because
    # SQLAlchemy already uses that name for ``Base.metadata``. Hence the
    # attribute rename, and hence the explicit column name here: without it
    # SQLAlchemy derives the column from the attribute and emits INSERTs
    # against an ``extra_data`` column that has never existed.
    #
    # That is not a theoretical mismatch. Every ``track_usage`` call raised
    # UndefinedColumnError in production, and because it shares a transaction
    # with the generation-history insert, both were rolled back — so no studio
    # build has ever been metered or recorded. It was silent because the caller
    # swallows telemetry failures by design.
    extra_data: Mapped[Optional[Dict[str, Any]]] = mapped_column("metadata", JSONB)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="usage_records")

    __table_args__ = (
        Index("ix_usage_records_user_action", "user_id", "action", "created_at"),
        Index("ix_usage_records_unreported", "reported_to_stripe", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<UsageRecord {self.action} by {self.user_id}>"
