"""
Database module for OrionFlow.

This module provides:
- SQLAlchemy async engine and session management
- Database models for users, designs, billing, etc.
- Connection pooling and health checks
"""

from app.db.session import (
    get_db,
    async_engine,
    AsyncSessionLocal,
    init_db,
    close_db,
)
from app.db.models import (
    Base,
    User,
    Design,
    GenerationHistory,
    APIKey,
    AuditLog,
    PricingPlan,
    Subscription,
    UsageRecord,
)

__all__ = [
    "get_db",
    "async_engine",
    "AsyncSessionLocal",
    "init_db",
    "close_db",
    "Base",
    "User",
    "Design",
    "GenerationHistory",
    "APIKey",
    "AuditLog",
    "PricingPlan",
    "Subscription",
    "UsageRecord",
]
