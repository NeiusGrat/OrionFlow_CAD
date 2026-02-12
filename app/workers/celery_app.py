"""
Celery application configuration for OrionFlow.

Provides async task processing for:
- CAD generation (long-running LLM + compilation)
- File exports
- Usage reporting
- Cleanup tasks
"""

from celery import Celery

from app.config import settings


def create_celery_app() -> Celery:
    """
    Create and configure Celery application.

    Returns:
        Configured Celery instance
    """
    celery = Celery(
        "orionflow",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=[
            "app.workers.tasks",
            "app.workers.scheduled_tasks",
        ],
    )

    # Celery configuration
    celery.conf.update(
        # Task settings
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,

        # Task execution
        task_acks_late=True,  # Acknowledge after task completes (for reliability)
        task_reject_on_worker_lost=True,
        task_time_limit=600,  # 10 minute hard limit
        task_soft_time_limit=540,  # 9 minute soft limit (for cleanup)

        # Result backend
        result_expires=86400,  # 24 hours
        result_extended=True,  # Store additional metadata

        # Worker settings
        worker_prefetch_multiplier=1,  # Only fetch one task at a time
        worker_concurrency=settings.celery_worker_concurrency,

        # Rate limiting
        task_default_rate_limit="100/m",

        # Monitoring
        worker_send_task_events=True,
        task_send_sent_event=True,

        # Routing
        task_routes={
            "app.workers.tasks.generate_cad_task": {"queue": "generation"},
            "app.workers.tasks.regenerate_cad_task": {"queue": "generation"},
            "app.workers.tasks.export_cad_task": {"queue": "export"},
            "app.workers.scheduled_tasks.*": {"queue": "scheduled"},
        },

        # Default queue
        task_default_queue="default",

        # Beat schedule (periodic tasks)
        beat_schedule={
            "cleanup-old-files": {
                "task": "app.workers.scheduled_tasks.cleanup_old_files",
                "schedule": 3600.0,  # Every hour
            },
            "report-usage-to-stripe": {
                "task": "app.workers.scheduled_tasks.report_usage",
                "schedule": 300.0,  # Every 5 minutes
            },
            "reset-monthly-usage": {
                "task": "app.workers.scheduled_tasks.reset_monthly_usage",
                "schedule": 86400.0,  # Daily check
            },
        },
    )

    return celery


# Create global Celery instance
celery_app = create_celery_app()


# Task base class with common functionality
class BaseTask(celery_app.Task):
    """Base task class with error handling and logging."""

    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        from app.logging_config import get_logger
        logger = get_logger(__name__)
        logger.error(
            "task_failed",
            task_id=task_id,
            task_name=self.name,
            exception=str(exc),
            traceback=str(einfo),
        )

    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success."""
        from app.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info(
            "task_completed",
            task_id=task_id,
            task_name=self.name,
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Handle task retry."""
        from app.logging_config import get_logger
        logger = get_logger(__name__)
        logger.warning(
            "task_retry",
            task_id=task_id,
            task_name=self.name,
            exception=str(exc),
        )
