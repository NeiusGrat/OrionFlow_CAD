"""
Celery tasks for CAD generation.

Tasks:
- generate_cad_task: Generate CAD from prompt
- regenerate_cad_task: Regenerate from edited feature graph
- export_cad_task: Export to additional formats
"""

import asyncio
from typing import Dict, Any, Optional
import uuid
from datetime import datetime, timezone

from celery import shared_task
from celery.utils.log import get_task_logger

from app.workers.celery_app import BaseTask
from app.config import settings

logger = get_task_logger(__name__)


def run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    base=BaseTask,
    name="app.workers.tasks.generate_cad_task",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def generate_cad_task(
    self,
    prompt: str,
    user_id: str,
    backend: str = "build123d",
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async task for CAD generation.

    Args:
        prompt: Natural language description
        user_id: User requesting generation
        backend: CAD backend to use
        job_id: Optional job ID (for tracking)

    Returns:
        Generation result with file paths and feature graph
    """
    job_id = job_id or str(uuid.uuid4())

    # Update task state with progress
    self.update_state(
        state="PROGRESS",
        meta={
            "job_id": job_id,
            "progress": 0,
            "stage": "initializing",
            "message": "Starting CAD generation...",
        }
    )

    try:
        # Stage 1: Parse and decompose prompt
        self.update_state(
            state="PROGRESS",
            meta={
                "job_id": job_id,
                "progress": 10,
                "stage": "parsing",
                "message": "Analyzing your design request...",
            }
        )

        async def _generate():
            from app.services.generation_service import GenerationService
            from app.db.session import get_db_context
            from app.db.models import GenerationHistory, GenerationStatus

            service = GenerationService(
                output_dir=settings.output_dir,
                use_v3_compiler=settings.use_v3_compiler,
                use_two_stage=settings.use_two_stage_pipeline,
            )

            # Create history record
            async with get_db_context() as db:
                history = GenerationHistory(
                    user_id=uuid.UUID(user_id),
                    prompt=prompt,
                    status=GenerationStatus.PROCESSING,
                )
                db.add(history)
                await db.commit()
                history_id = history.id

            try:
                # Generate CAD
                result = await service.generate(prompt, backend=backend)

                # Update history with success
                async with get_db_context() as db:
                    from sqlalchemy import select
                    stmt = select(GenerationHistory).where(GenerationHistory.id == history_id)
                    result_row = await db.execute(stmt)
                    history = result_row.scalar_one()

                    history.status = GenerationStatus.COMPLETED
                    history.feature_graph = result.metadata.get("feature_graph", {})
                    history.completed_at = datetime.now(timezone.utc)
                    history.duration_ms = int(
                        (history.completed_at - history.created_at).total_seconds() * 1000
                    )
                    await db.commit()

                # Track usage
                from app.billing.usage import track_usage
                async with get_db_context() as db:
                    await track_usage(
                        db,
                        uuid.UUID(user_id),
                        action="generation",
                        metadata={"job_id": job_id, "prompt_length": len(prompt)},
                    )

                return result

            except Exception as e:
                # Update history with failure
                async with get_db_context() as db:
                    from sqlalchemy import select
                    stmt = select(GenerationHistory).where(GenerationHistory.id == history_id)
                    result_row = await db.execute(stmt)
                    history = result_row.scalar_one()

                    history.status = GenerationStatus.FAILED
                    history.error_message = str(e)
                    history.completed_at = datetime.now(timezone.utc)
                    await db.commit()

                raise

        result = run_async(_generate())

        # Stage 2: Update progress
        self.update_state(
            state="PROGRESS",
            meta={
                "job_id": job_id,
                "progress": 100,
                "stage": "completed",
                "message": "CAD generation complete!",
            }
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "model_id": result.metadata["job_id"],
            "viewer": {
                "glb_url": str(result.geometry_path).replace("\\", "/"),
            },
            "downloads": {
                "step": str(result.metadata.get("step_path", "")).replace("\\", "/"),
                "stl": str(result.metadata.get("stl_path", "")).replace("\\", "/"),
            },
            "cfg": result.metadata.get("feature_graph", {}),
        }

    except Exception as e:
        logger.error(f"CAD generation failed: {e}")

        # Re-raise for Celery retry mechanism
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)

        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(e),
        }


@shared_task(
    bind=True,
    base=BaseTask,
    name="app.workers.tasks.regenerate_cad_task",
    max_retries=2,
)
def regenerate_cad_task(
    self,
    feature_graph: Dict[str, Any],
    user_id: str,
    prompt: str = "",
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async task for CAD regeneration from edited feature graph.

    Args:
        feature_graph: Edited feature graph JSON
        user_id: User requesting regeneration
        prompt: Optional edit prompt
        job_id: Optional job ID

    Returns:
        Regeneration result
    """
    job_id = job_id or str(uuid.uuid4())

    self.update_state(
        state="PROGRESS",
        meta={
            "job_id": job_id,
            "progress": 0,
            "stage": "initializing",
            "message": "Starting regeneration...",
        }
    )

    try:
        async def _regenerate():
            from app.services.generation_service import GenerationService

            service = GenerationService(
                output_dir=settings.output_dir,
                use_v3_compiler=settings.use_v3_compiler,
            )

            result = await service.regenerate(feature_graph, prompt)
            return result

        result = run_async(_regenerate())

        return {
            "job_id": job_id,
            "status": "completed",
            "model_id": result.metadata["job_id"],
            "viewer": {
                "glb_url": str(result.geometry_path).replace("\\", "/"),
            },
            "downloads": {
                "step": str(result.metadata.get("step_path", "")).replace("\\", "/"),
                "stl": str(result.metadata.get("stl_path", "")).replace("\\", "/"),
            },
            "cfg": result.metadata.get("feature_graph", {}),
        }

    except Exception as e:
        logger.error(f"CAD regeneration failed: {e}")
        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(e),
        }


@shared_task(
    bind=True,
    base=BaseTask,
    name="app.workers.tasks.export_cad_task",
)
def export_cad_task(
    self,
    job_id: str,
    formats: list = None,
    user_id: str = None,
) -> Dict[str, Any]:
    """
    Export CAD model to additional formats.

    Args:
        job_id: Original generation job ID
        formats: List of formats to export (step, stl, glb, obj)
        user_id: User requesting export

    Returns:
        Export results with file paths
    """
    formats = formats or ["step", "stl", "glb"]

    self.update_state(
        state="PROGRESS",
        meta={
            "job_id": job_id,
            "progress": 0,
            "stage": "exporting",
            "message": f"Exporting to {', '.join(formats)}...",
        }
    )

    try:
        # Export logic would go here
        # For now, return existing paths
        from pathlib import Path

        output_dir = settings.output_dir
        results = {}

        for fmt in formats:
            path = output_dir / f"{job_id}.{fmt}"
            if path.exists():
                results[fmt] = str(path).replace("\\", "/")

        return {
            "job_id": job_id,
            "status": "completed",
            "exports": results,
        }

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(e),
        }


def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get status of a running task.

    Args:
        task_id: Celery task ID

    Returns:
        Task status and metadata
    """
    from celery.result import AsyncResult
    from app.workers.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING":
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "Task is waiting to be processed",
        }
    elif result.state == "PROGRESS":
        return {
            "task_id": task_id,
            "status": "processing",
            **result.info,
        }
    elif result.state == "SUCCESS":
        return {
            "task_id": task_id,
            "status": "completed",
            "result": result.result,
        }
    elif result.state == "FAILURE":
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(result.info),
        }
    else:
        return {
            "task_id": task_id,
            "status": result.state.lower(),
        }
