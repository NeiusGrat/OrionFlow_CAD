"""
Usage tracking and metering for OrionFlow.

Handles:
- Tracking CAD generations
- Usage limit enforcement
- Monthly reset cycles
- Stripe usage reporting (for metered billing)
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.models import User, Subscription, PricingPlan, UsageRecord
from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


async def track_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str = "generation",
    quantity: int = 1,
    metadata: Optional[Dict[str, Any]] = None,
) -> UsageRecord:
    """
    Track a usage event.

    Args:
        db: Database session
        user_id: User who performed the action
        action: Type of action (e.g., "generation")
        quantity: Number of units consumed
        metadata: Additional data about the usage

    Returns:
        Created UsageRecord
    """
    record = UsageRecord(
        user_id=user_id,
        action=action,
        quantity=quantity,
        extra_data=metadata or {},
    )
    db.add(record)

    # Update subscription usage counter
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    subscription = result.scalar_one_or_none()

    if subscription:
        subscription.generations_used += quantity

    await db.commit()
    await db.refresh(record)

    logger.info(
        "usage_tracked",
        user_id=str(user_id),
        action=action,
        quantity=quantity
    )

    return record


async def get_usage_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Get usage statistics for a user.

    Args:
        db: Database session
        user_id: User to get stats for
        start_date: Start of period (default: start of current month)
        end_date: End of period (default: now)

    Returns:
        Usage statistics
    """
    # Default to current month
    now = datetime.now(timezone.utc)
    if start_date is None:
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if end_date is None:
        end_date = now

    # Get subscription for limits
    result = await db.execute(
        select(Subscription, PricingPlan)
        .join(PricingPlan, Subscription.plan_id == PricingPlan.id)
        .where(Subscription.user_id == user_id)
    )
    row = result.one_or_none()

    if row:
        subscription, plan = row
        limit = plan.generations_per_month
        used = subscription.generations_used
    else:
        # Free tier defaults
        limit = settings.free_tier_generations
        # Count usage for free users
        result = await db.execute(
            select(func.sum(UsageRecord.quantity))
            .where(
                UsageRecord.user_id == user_id,
                UsageRecord.action == "generation",
                UsageRecord.created_at >= start_date,
                UsageRecord.created_at <= end_date,
            )
        )
        used = result.scalar() or 0

    # Get daily breakdown
    result = await db.execute(
        select(
            func.date(UsageRecord.created_at).label("date"),
            func.sum(UsageRecord.quantity).label("count")
        )
        .where(
            UsageRecord.user_id == user_id,
            UsageRecord.action == "generation",
            UsageRecord.created_at >= start_date,
            UsageRecord.created_at <= end_date,
        )
        .group_by(func.date(UsageRecord.created_at))
        .order_by(func.date(UsageRecord.created_at))
    )
    daily_usage = [{"date": row.date.isoformat(), "count": row.count} for row in result.all()]

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "generations": {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "percentage": min(100, (used / limit) * 100) if limit > 0 else 100,
        },
        "daily_usage": daily_usage,
    }


async def check_usage_limit(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Dict[str, Any]:
    """
    Check if a user can perform a generation.

    Args:
        db: Database session
        user_id: User to check

    Returns:
        Dict with allowed status and details
    """
    # Get subscription
    result = await db.execute(
        select(Subscription, PricingPlan)
        .join(PricingPlan, Subscription.plan_id == PricingPlan.id)
        .where(Subscription.user_id == user_id)
    )
    row = result.one_or_none()

    if row:
        subscription, plan = row

        # Check if subscription is active
        if subscription.status.value not in ["active", "trialing"]:
            return {
                "allowed": False,
                "reason": "subscription_inactive",
                "message": "Your subscription is not active. Please update your payment method.",
            }

        # Check usage limit
        if subscription.generations_used >= plan.generations_per_month:
            return {
                "allowed": False,
                "reason": "limit_reached",
                "message": f"You've reached your monthly limit of {plan.generations_per_month} generations.",
                "used": subscription.generations_used,
                "limit": plan.generations_per_month,
                "resets_at": subscription.current_period_end.isoformat(),
            }

        return {
            "allowed": True,
            "used": subscription.generations_used,
            "limit": plan.generations_per_month,
            "remaining": plan.generations_per_month - subscription.generations_used,
        }

    # Free tier - check against default limit
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(func.sum(UsageRecord.quantity))
        .where(
            UsageRecord.user_id == user_id,
            UsageRecord.action == "generation",
            UsageRecord.created_at >= start_of_month,
        )
    )
    used = result.scalar() or 0
    limit = settings.free_tier_generations

    if used >= limit:
        return {
            "allowed": False,
            "reason": "free_tier_limit_reached",
            "message": f"You've reached the free tier limit of {limit} generations per month. Upgrade for more.",
            "used": used,
            "limit": limit,
        }

    return {
        "allowed": True,
        "used": used,
        "limit": limit,
        "remaining": limit - used,
    }


async def reset_monthly_usage(
    db: AsyncSession,
    subscription_id: uuid.UUID,
) -> bool:
    """
    Reset monthly usage counter for a subscription.

    Called by billing cycle webhook or scheduled job.

    Args:
        db: Database session
        subscription_id: Subscription to reset

    Returns:
        True if successful
    """
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        return False

    # Reset counter
    old_usage = subscription.generations_used
    subscription.generations_used = 0

    # Update billing period
    subscription.current_period_start = datetime.now(timezone.utc)
    subscription.current_period_end = subscription.current_period_start + timedelta(days=30)

    await db.commit()

    logger.info(
        "monthly_usage_reset",
        subscription_id=str(subscription_id),
        old_usage=old_usage
    )

    return True


async def report_usage_to_stripe(
    db: AsyncSession,
    subscription_id: uuid.UUID,
) -> bool:
    """
    Report unreported usage to Stripe for metered billing.

    Args:
        db: Database session
        subscription_id: Subscription to report usage for

    Returns:
        True if successful
    """
    import stripe
    from app.config import settings

    stripe.api_key = settings.stripe_secret_key

    # Get subscription
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription or not subscription.stripe_subscription_id:
        return False

    # Get unreported usage records
    result = await db.execute(
        select(UsageRecord)
        .where(
            UsageRecord.user_id == subscription.user_id,
            UsageRecord.reported_to_stripe == False,
            UsageRecord.billable == True,
        )
    )
    records = result.scalars().all()

    if not records:
        return True  # Nothing to report

    # Get subscription item ID for metered billing
    try:
        stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
        subscription_item_id = stripe_sub["items"]["data"][0]["id"]
    except Exception as e:
        logger.error(
            "stripe_subscription_retrieve_failed",
            subscription_id=str(subscription_id),
            error=str(e)
        )
        return False

    # Report each record
    for record in records:
        try:
            usage_record = stripe.SubscriptionItem.create_usage_record(
                subscription_item_id,
                quantity=record.quantity,
                timestamp=int(record.created_at.timestamp()),
                action="increment",
            )
            record.reported_to_stripe = True
            record.stripe_usage_record_id = usage_record.id

        except Exception as e:
            logger.error(
                "stripe_usage_report_failed",
                record_id=str(record.id),
                error=str(e)
            )

    await db.commit()

    logger.info(
        "usage_reported_to_stripe",
        subscription_id=str(subscription_id),
        records_count=len(records)
    )

    return True
