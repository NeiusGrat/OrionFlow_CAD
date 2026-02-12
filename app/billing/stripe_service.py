"""
Stripe payment integration for OrionFlow.

Handles:
- Customer creation and management
- Checkout session creation
- Subscription management
- Customer portal sessions
- Webhook event processing
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid

import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.models import User, Subscription, PricingPlan, SubscriptionStatus
from app.logging_config import get_logger

logger = get_logger(__name__)

# Initialize Stripe with API key
stripe.api_key = settings.stripe_secret_key


class StripeService:
    """Service class for Stripe operations."""

    @staticmethod
    async def create_customer(
        db: AsyncSession,
        user: User,
    ) -> str:
        """
        Create a Stripe customer for a user.

        Args:
            db: Database session
            user: User to create customer for

        Returns:
            Stripe customer ID
        """
        try:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.name,
                metadata={
                    "user_id": str(user.id),
                    "created_by": "orionflow",
                }
            )

            logger.info(
                "stripe_customer_created",
                user_id=str(user.id),
                customer_id=customer.id
            )

            return customer.id

        except stripe.error.StripeError as e:
            logger.error(
                "stripe_customer_creation_failed",
                user_id=str(user.id),
                error=str(e)
            )
            raise

    @staticmethod
    async def create_checkout_session(
        db: AsyncSession,
        user: User,
        plan_id: uuid.UUID,
        billing_period: str = "monthly",
        success_url: str = None,
        cancel_url: str = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout session for subscription.

        Args:
            db: Database session
            user: User subscribing
            plan_id: Pricing plan ID
            billing_period: "monthly" or "yearly"
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancellation

        Returns:
            Checkout session details with URL
        """
        # Get pricing plan
        result = await db.execute(
            select(PricingPlan).where(PricingPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()

        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")

        # Get or create Stripe customer
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if subscription and subscription.stripe_customer_id:
            customer_id = subscription.stripe_customer_id
        else:
            customer_id = await StripeService.create_customer(db, user)

        # Get price ID based on billing period
        price_id = (
            plan.stripe_price_id_monthly
            if billing_period == "monthly"
            else plan.stripe_price_id_yearly
        )

        if not price_id:
            raise ValueError(f"No Stripe price configured for plan: {plan.name}")

        # Create checkout session
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url or f"{settings.frontend_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url or f"{settings.frontend_url}/billing/cancel",
                metadata={
                    "user_id": str(user.id),
                    "plan_id": str(plan_id),
                    "billing_period": billing_period,
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user.id),
                        "plan_id": str(plan_id),
                    }
                },
                allow_promotion_codes=True,
            )

            logger.info(
                "checkout_session_created",
                user_id=str(user.id),
                session_id=session.id
            )

            return {
                "session_id": session.id,
                "url": session.url,
            }

        except stripe.error.StripeError as e:
            logger.error(
                "checkout_session_creation_failed",
                user_id=str(user.id),
                error=str(e)
            )
            raise

    @staticmethod
    async def create_portal_session(
        db: AsyncSession,
        user: User,
        return_url: str = None,
    ) -> Dict[str, str]:
        """
        Create a Stripe Customer Portal session.

        Allows users to manage their subscription.

        Args:
            db: Database session
            user: User accessing portal
            return_url: URL to return to after portal

        Returns:
            Portal session URL
        """
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_customer_id:
            raise ValueError("User has no subscription")

        try:
            session = stripe.billing_portal.Session.create(
                customer=subscription.stripe_customer_id,
                return_url=return_url or f"{settings.frontend_url}/billing",
            )

            return {"url": session.url}

        except stripe.error.StripeError as e:
            logger.error(
                "portal_session_creation_failed",
                user_id=str(user.id),
                error=str(e)
            )
            raise

    @staticmethod
    async def cancel_subscription(
        db: AsyncSession,
        user: User,
        at_period_end: bool = True,
    ) -> bool:
        """
        Cancel a user's subscription.

        Args:
            db: Database session
            user: User cancelling
            at_period_end: If True, cancel at end of period; if False, cancel immediately

        Returns:
            True if successful
        """
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_subscription_id:
            raise ValueError("User has no active subscription")

        try:
            if at_period_end:
                stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
                subscription.cancel_at_period_end = True
            else:
                stripe.Subscription.cancel(subscription.stripe_subscription_id)
                subscription.status = SubscriptionStatus.CANCELLED

            subscription.cancelled_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(
                "subscription_cancelled",
                user_id=str(user.id),
                at_period_end=at_period_end
            )

            return True

        except stripe.error.StripeError as e:
            logger.error(
                "subscription_cancellation_failed",
                user_id=str(user.id),
                error=str(e)
            )
            raise

    @staticmethod
    async def get_subscription(
        db: AsyncSession,
        user: User,
    ) -> Optional[Dict[str, Any]]:
        """
        Get subscription details for a user.

        Args:
            db: Database session
            user: User to check

        Returns:
            Subscription details or None
        """
        result = await db.execute(
            select(Subscription, PricingPlan)
            .join(PricingPlan, Subscription.plan_id == PricingPlan.id)
            .where(Subscription.user_id == user.id)
        )
        row = result.one_or_none()

        if not row:
            return None

        subscription, plan = row

        return {
            "id": str(subscription.id),
            "plan": {
                "id": str(plan.id),
                "name": plan.name,
                "display_name": plan.display_name,
                "price_monthly": plan.price_monthly_cents / 100,
                "price_yearly": plan.price_yearly_cents / 100,
                "generations_per_month": plan.generations_per_month,
                "max_designs": plan.max_designs,
                "features": plan.features,
            },
            "status": subscription.status.value,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": subscription.current_period_end.isoformat(),
            "generations_used": subscription.generations_used,
            "cancel_at_period_end": subscription.cancel_at_period_end,
        }


# Convenience functions
async def create_customer(db: AsyncSession, user: User) -> str:
    """Create a Stripe customer."""
    return await StripeService.create_customer(db, user)


async def create_checkout_session(
    db: AsyncSession,
    user: User,
    plan_id: uuid.UUID,
    billing_period: str = "monthly",
    **kwargs
) -> Dict[str, Any]:
    """Create a checkout session."""
    return await StripeService.create_checkout_session(
        db, user, plan_id, billing_period, **kwargs
    )


async def create_portal_session(
    db: AsyncSession,
    user: User,
    **kwargs
) -> Dict[str, str]:
    """Create a customer portal session."""
    return await StripeService.create_portal_session(db, user, **kwargs)


async def cancel_subscription(
    db: AsyncSession,
    user: User,
    at_period_end: bool = True,
) -> bool:
    """Cancel a subscription."""
    return await StripeService.cancel_subscription(db, user, at_period_end)


async def get_subscription(
    db: AsyncSession,
    user: User,
) -> Optional[Dict[str, Any]]:
    """Get subscription details."""
    return await StripeService.get_subscription(db, user)
