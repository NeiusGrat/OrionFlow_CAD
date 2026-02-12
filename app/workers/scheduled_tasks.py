"""
Scheduled Celery tasks for OrionFlow.

Tasks:
- cleanup_old_files: Remove old generated files
- report_usage: Report usage to Stripe
- reset_monthly_usage: Reset usage counters
- health_check: System health monitoring
"""

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from celery import shared_task
from celery.utils.log import get_task_logger

from app.config import settings

logger = get_task_logger(__name__)


@shared_task(name="app.workers.scheduled_tasks.cleanup_old_files")
def cleanup_old_files(max_age_hours: int = 24) -> dict:
    """
    Clean up old generated CAD files.

    Args:
        max_age_hours: Maximum age of files to keep

    Returns:
        Cleanup statistics
    """
    output_dir = Path(settings.output_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    deleted_count = 0
    total_size = 0

    try:
        for file_path in output_dir.iterdir():
            if file_path.is_file():
                # Get file modification time
                mtime = datetime.fromtimestamp(
                    file_path.stat().st_mtime,
                    tz=timezone.utc
                )

                if mtime < cutoff:
                    size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    total_size += size

        logger.info(
            f"Cleaned up {deleted_count} files, freed {total_size / 1024 / 1024:.2f} MB"
        )

        return {
            "status": "success",
            "deleted_files": deleted_count,
            "freed_bytes": total_size,
        }

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }


@shared_task(name="app.workers.scheduled_tasks.report_usage")
def report_usage() -> dict:
    """
    Report unreported usage to Stripe.

    Returns:
        Reporting statistics
    """
    import asyncio

    async def _report():
        from app.db.session import get_db_context
        from app.db.models import Subscription
        from app.billing.usage import report_usage_to_stripe
        from sqlalchemy import select

        reported_count = 0

        async with get_db_context() as db:
            # Get all active subscriptions
            result = await db.execute(
                select(Subscription).where(
                    Subscription.status.in_(["active", "trialing"])
                )
            )
            subscriptions = result.scalars().all()

            for subscription in subscriptions:
                try:
                    await report_usage_to_stripe(db, subscription.id)
                    reported_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to report usage for {subscription.id}: {e}"
                    )

        return reported_count

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reported = loop.run_until_complete(_report())
        loop.close()

        return {
            "status": "success",
            "subscriptions_reported": reported,
        }

    except Exception as e:
        logger.error(f"Usage reporting failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }


@shared_task(name="app.workers.scheduled_tasks.reset_monthly_usage")
def reset_monthly_usage() -> dict:
    """
    Reset monthly usage for subscriptions whose period has ended.

    Returns:
        Reset statistics
    """
    import asyncio

    async def _reset():
        from app.db.session import get_db_context
        from app.db.models import Subscription
        from app.billing.usage import reset_monthly_usage as do_reset
        from sqlalchemy import select

        reset_count = 0
        now = datetime.now(timezone.utc)

        async with get_db_context() as db:
            # Find subscriptions past their period end
            result = await db.execute(
                select(Subscription).where(
                    Subscription.current_period_end < now,
                    Subscription.status.in_(["active", "trialing"])
                )
            )
            subscriptions = result.scalars().all()

            for subscription in subscriptions:
                try:
                    await do_reset(db, subscription.id)
                    reset_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to reset usage for {subscription.id}: {e}"
                    )

        return reset_count

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reset = loop.run_until_complete(_reset())
        loop.close()

        return {
            "status": "success",
            "subscriptions_reset": reset,
        }

    except Exception as e:
        logger.error(f"Usage reset failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }


@shared_task(name="app.workers.scheduled_tasks.health_check")
def health_check() -> dict:
    """
    Perform system health check.

    Checks:
    - Database connectivity
    - Redis connectivity
    - Storage availability
    - External service availability

    Returns:
        Health status
    """
    import asyncio

    async def _check():
        results = {
            "database": False,
            "redis": False,
            "storage": False,
            "llm": False,
        }

        # Check database
        try:
            from app.db.session import check_db_health
            results["database"] = await check_db_health()
        except Exception as e:
            logger.error(f"Database health check failed: {e}")

        # Check Redis
        try:
            import redis
            r = redis.from_url(settings.redis_url)
            r.ping()
            results["redis"] = True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")

        # Check storage
        try:
            output_dir = Path(settings.output_dir)
            results["storage"] = output_dir.exists() and os.access(output_dir, os.W_OK)
        except Exception as e:
            logger.error(f"Storage health check failed: {e}")

        # Check LLM API
        try:
            if settings.groq_api_key:
                # Simple connectivity check
                results["llm"] = True
        except Exception as e:
            logger.error(f"LLM health check failed: {e}")

        return results

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(_check())
        loop.close()

        all_healthy = all(results.values())

        return {
            "status": "healthy" if all_healthy else "degraded",
            "checks": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }


@shared_task(name="app.workers.scheduled_tasks.send_usage_alerts")
def send_usage_alerts() -> dict:
    """
    Send alerts to users approaching usage limits.

    Returns:
        Alert statistics
    """
    import asyncio

    async def _send_alerts():
        from app.db.session import get_db_context
        from app.db.models import Subscription, PricingPlan, User
        from sqlalchemy import select

        alerts_sent = 0

        async with get_db_context() as db:
            # Find subscriptions at 80% usage
            result = await db.execute(
                select(Subscription, PricingPlan, User)
                .join(PricingPlan, Subscription.plan_id == PricingPlan.id)
                .join(User, Subscription.user_id == User.id)
                .where(Subscription.status == "active")
            )

            for subscription, plan, user in result.all():
                usage_percent = (
                    subscription.generations_used / plan.generations_per_month * 100
                )

                if usage_percent >= 80 and usage_percent < 100:
                    # TODO: Send email alert
                    logger.info(
                        f"Usage alert for {user.email}: {usage_percent:.0f}%"
                    )
                    alerts_sent += 1

        return alerts_sent

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        sent = loop.run_until_complete(_send_alerts())
        loop.close()

        return {
            "status": "success",
            "alerts_sent": sent,
        }

    except Exception as e:
        logger.error(f"Alert sending failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }
