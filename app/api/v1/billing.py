"""
Billing API endpoints.

Endpoints:
- GET /plans - List available plans
- GET /subscription - Get current subscription
- POST /checkout - Create checkout session
- POST /portal - Create customer portal session
- POST /cancel - Cancel subscription
- GET /usage - Get usage statistics
- POST /webhooks/stripe - Stripe webhook handler
"""

from typing import List, Optional
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, PricingPlan, Subscription
from app.auth.dependencies import get_current_active_user
from app.billing.stripe_service import (
    create_checkout_session,
    create_portal_session,
    cancel_subscription,
    get_subscription,
)
from app.billing.usage import get_usage_stats, check_usage_limit
from app.billing.webhooks import verify_webhook_signature, process_webhook_event
from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class PlanResponse(BaseModel):
    """Pricing plan response."""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    price_monthly: float
    price_yearly: float
    generations_per_month: int
    max_designs: int
    features: dict
    is_active: bool


class SubscriptionResponse(BaseModel):
    """Subscription response."""
    id: str
    plan: PlanResponse
    status: str
    current_period_start: str
    current_period_end: str
    generations_used: int
    cancel_at_period_end: bool


class CheckoutRequest(BaseModel):
    """Checkout session request."""
    plan_id: str
    billing_period: str = Field("monthly", pattern="^(monthly|yearly)$")
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CheckoutResponse(BaseModel):
    """Checkout session response."""
    session_id: str
    url: str


class PortalResponse(BaseModel):
    """Customer portal response."""
    url: str


class UsageResponse(BaseModel):
    """Usage statistics response."""
    period: dict
    generations: dict
    daily_usage: List[dict]


class UsageLimitResponse(BaseModel):
    """Usage limit check response."""
    allowed: bool
    reason: Optional[str] = None
    message: Optional[str] = None
    used: int
    limit: int
    remaining: int


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get(
    "/plans",
    response_model=List[PlanResponse],
    summary="List available plans",
)
async def list_plans(
    db: AsyncSession = Depends(get_db),
):
    """
    List all available pricing plans.
    """
    result = await db.execute(
        select(PricingPlan)
        .where(PricingPlan.is_active == True, PricingPlan.is_public == True)
        .order_by(PricingPlan.price_monthly_cents)
    )
    plans = result.scalars().all()

    return [
        PlanResponse(
            id=str(p.id),
            name=p.name,
            display_name=p.display_name,
            description=p.description,
            price_monthly=p.price_monthly_cents / 100,
            price_yearly=p.price_yearly_cents / 100,
            generations_per_month=p.generations_per_month,
            max_designs=p.max_designs,
            features=p.features,
            is_active=p.is_active,
        )
        for p in plans
    ]


@router.get(
    "/subscription",
    response_model=Optional[SubscriptionResponse],
    summary="Get current subscription",
)
async def get_current_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current user's subscription details.
    """
    subscription_data = await get_subscription(db, current_user)

    if not subscription_data:
        return None

    return SubscriptionResponse(
        id=subscription_data["id"],
        plan=PlanResponse(
            id=subscription_data["plan"]["id"],
            name=subscription_data["plan"]["name"],
            display_name=subscription_data["plan"]["display_name"],
            description=None,
            price_monthly=subscription_data["plan"]["price_monthly"],
            price_yearly=subscription_data["plan"]["price_yearly"],
            generations_per_month=subscription_data["plan"]["generations_per_month"],
            max_designs=subscription_data["plan"]["max_designs"],
            features=subscription_data["plan"]["features"],
            is_active=True,
        ),
        status=subscription_data["status"],
        current_period_start=subscription_data["current_period_start"],
        current_period_end=subscription_data["current_period_end"],
        generations_used=subscription_data["generations_used"],
        cancel_at_period_end=subscription_data["cancel_at_period_end"],
    )


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Create checkout session",
)
async def create_checkout(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Stripe Checkout session for subscription.
    """
    try:
        plan_uuid = uuid.UUID(request.plan_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plan ID"
        )

    try:
        session = await create_checkout_session(
            db=db,
            user=current_user,
            plan_id=plan_uuid,
            billing_period=request.billing_period,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )

        return CheckoutResponse(
            session_id=session["session_id"],
            url=session["url"],
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Checkout session creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )


@router.post(
    "/portal",
    response_model=PortalResponse,
    summary="Create customer portal session",
)
async def create_portal(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Stripe Customer Portal session for subscription management.
    """
    try:
        session = await create_portal_session(db=db, user=current_user)
        return PortalResponse(url=session["url"])

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Portal session creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create portal session"
        )


@router.post(
    "/cancel",
    response_model=MessageResponse,
    summary="Cancel subscription",
)
async def cancel_user_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel the current user's subscription at the end of the billing period.
    """
    try:
        await cancel_subscription(db=db, user=current_user, at_period_end=True)
        return MessageResponse(
            message="Subscription will be cancelled at the end of the billing period"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Subscription cancellation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription"
        )


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Get usage statistics",
)
async def get_user_usage(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get usage statistics for the current user.
    """
    stats = await get_usage_stats(db, current_user.id)

    return UsageResponse(
        period=stats["period"],
        generations=stats["generations"],
        daily_usage=stats["daily_usage"],
    )


@router.get(
    "/usage/check",
    response_model=UsageLimitResponse,
    summary="Check usage limit",
)
async def check_user_limit(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if the user can perform a generation.
    """
    result = await check_usage_limit(db, current_user.id)

    return UsageLimitResponse(
        allowed=result["allowed"],
        reason=result.get("reason"),
        message=result.get("message"),
        used=result.get("used", 0),
        limit=result.get("limit", 0),
        remaining=result.get("remaining", 0),
    )


@router.post(
    "/webhooks/stripe",
    include_in_schema=False,
    summary="Stripe webhook handler",
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Stripe webhook events.

    This endpoint is called by Stripe when subscription events occur.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header"
        )

    # Get raw body for signature verification
    payload = await request.body()

    try:
        event = verify_webhook_signature(payload, stripe_signature)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature"
        )

    # Process the event
    try:
        await process_webhook_event(db, event)
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        # Return 200 to prevent Stripe from retrying
        return {"status": "error", "message": str(e)}
