"""
Stripe webhook handlers for OrionFlow.

Handles:
- Checkout session completion
- Subscription updates
- Invoice events
- Payment failures
"""

from typing import Dict, Any
from datetime import datetime, timezone
import uuid

import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.models import User, Subscription, PricingPlan, SubscriptionStatus
from app.logging_config import get_logger

logger = get_logger(__name__)


async def handle_checkout_session_completed(
    db: AsyncSession,
    event: Dict[str, Any],
) -> bool:
    """
    Handle checkout.session.completed event.

    Creates or updates subscription after successful checkout.

    Args:
        db: Database session
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    session = event["data"]["object"]

    # Extract metadata
    user_id = session["metadata"].get("user_id")
    plan_id = session["metadata"].get("plan_id")

    if not user_id or not plan_id:
        logger.error("checkout_session_missing_metadata", session_id=session["id"])
        return False

    # Get or create subscription
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == uuid.UUID(user_id))
    )
    subscription = result.scalar_one_or_none()

    if subscription:
        # Update existing subscription
        subscription.plan_id = uuid.UUID(plan_id)
        subscription.stripe_customer_id = session["customer"]
        subscription.stripe_subscription_id = session["subscription"]
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.generations_used = 0
        subscription.current_period_start = datetime.now(timezone.utc)
    else:
        # Create new subscription
        # Get plan for period end
        result = await db.execute(
            select(PricingPlan).where(PricingPlan.id == uuid.UUID(plan_id))
        )
        plan = result.scalar_one()

        subscription = Subscription(
            user_id=uuid.UUID(user_id),
            plan_id=uuid.UUID(plan_id),
            stripe_customer_id=session["customer"],
            stripe_subscription_id=session["subscription"],
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc),  # Will be updated by invoice event
        )
        db.add(subscription)

    # Update user status to active
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user:
        from app.db.models import UserStatus
        user.status = UserStatus.ACTIVE

    await db.commit()

    logger.info(
        "checkout_completed",
        user_id=user_id,
        plan_id=plan_id,
        subscription_id=session["subscription"]
    )

    return True


async def handle_subscription_updated(
    db: AsyncSession,
    event: Dict[str, Any],
) -> bool:
    """
    Handle customer.subscription.updated event.

    Updates subscription status and billing period.

    Args:
        db: Database session
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    stripe_sub = event["data"]["object"]

    # Find subscription by Stripe ID
    result = await db.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_sub["id"]
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning("subscription_not_found", stripe_subscription_id=stripe_sub["id"])
        return False

    # Update status
    status_map = {
        "active": SubscriptionStatus.ACTIVE,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELLED,
        "trialing": SubscriptionStatus.TRIALING,
        "paused": SubscriptionStatus.PAUSED,
    }
    subscription.status = status_map.get(
        stripe_sub["status"],
        SubscriptionStatus.ACTIVE
    )

    # Update billing period
    subscription.current_period_start = datetime.fromtimestamp(
        stripe_sub["current_period_start"],
        tz=timezone.utc
    )
    subscription.current_period_end = datetime.fromtimestamp(
        stripe_sub["current_period_end"],
        tz=timezone.utc
    )

    # Handle cancellation
    subscription.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)

    await db.commit()

    logger.info(
        "subscription_updated",
        subscription_id=str(subscription.id),
        status=subscription.status.value
    )

    return True


async def handle_subscription_deleted(
    db: AsyncSession,
    event: Dict[str, Any],
) -> bool:
    """
    Handle customer.subscription.deleted event.

    Marks subscription as cancelled.

    Args:
        db: Database session
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    stripe_sub = event["data"]["object"]

    result = await db.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_sub["id"]
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning("subscription_not_found", stripe_subscription_id=stripe_sub["id"])
        return False

    subscription.status = SubscriptionStatus.CANCELLED
    subscription.cancelled_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "subscription_deleted",
        subscription_id=str(subscription.id)
    )

    return True


async def handle_invoice_paid(
    db: AsyncSession,
    event: Dict[str, Any],
) -> bool:
    """
    Handle invoice.paid event.

    Resets usage counters for new billing period.

    Args:
        db: Database session
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        return True  # One-time payment, not subscription

    result = await db.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == subscription_id
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning("subscription_not_found", stripe_subscription_id=subscription_id)
        return False

    # Reset usage for new period
    subscription.generations_used = 0
    subscription.status = SubscriptionStatus.ACTIVE

    # Update period dates from invoice lines
    if invoice.get("lines", {}).get("data"):
        line = invoice["lines"]["data"][0]
        subscription.current_period_start = datetime.fromtimestamp(
            line["period"]["start"],
            tz=timezone.utc
        )
        subscription.current_period_end = datetime.fromtimestamp(
            line["period"]["end"],
            tz=timezone.utc
        )

    await db.commit()

    logger.info(
        "invoice_paid_usage_reset",
        subscription_id=str(subscription.id)
    )

    return True


async def handle_invoice_payment_failed(
    db: AsyncSession,
    event: Dict[str, Any],
) -> bool:
    """
    Handle invoice.payment_failed event.

    Updates subscription status to past_due.

    Args:
        db: Database session
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        return True

    result = await db.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == subscription_id
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning("subscription_not_found", stripe_subscription_id=subscription_id)
        return False

    subscription.status = SubscriptionStatus.PAST_DUE

    await db.commit()

    logger.warning(
        "payment_failed",
        subscription_id=str(subscription.id),
        user_id=str(subscription.user_id)
    )

    # TODO: Send payment failure email to user

    return True


# Webhook handler dispatcher
WEBHOOK_HANDLERS = {
    "checkout.session.completed": handle_checkout_session_completed,
    "customer.subscription.updated": handle_subscription_updated,
    "customer.subscription.deleted": handle_subscription_deleted,
    "invoice.paid": handle_invoice_paid,
    "invoice.payment_failed": handle_invoice_payment_failed,
}


async def process_webhook_event(
    db: AsyncSession,
    event: Dict[str, Any],
) -> bool:
    """
    Process a Stripe webhook event.

    Args:
        db: Database session
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    event_type = event["type"]

    handler = WEBHOOK_HANDLERS.get(event_type)
    if handler:
        return await handler(db, event)

    logger.debug("unhandled_webhook_event", event_type=event_type)
    return True  # Not an error, just unhandled


def verify_webhook_signature(
    payload: bytes,
    signature: str,
) -> Dict[str, Any]:
    """
    Verify Stripe webhook signature.

    Args:
        payload: Raw request body
        signature: Stripe-Signature header value

    Returns:
        Verified event object

    Raises:
        ValueError: If signature verification fails
    """
    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret,
        )
        return event
    except stripe.error.SignatureVerificationError as e:
        logger.error("webhook_signature_invalid", error=str(e))
        raise ValueError("Invalid webhook signature")
