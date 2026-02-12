"""
Job management API endpoints for async CAD generation.

Endpoints:
- POST /generate - Start async CAD generation
- GET /{job_id} - Get job status
- DELETE /{job_id} - Cancel job
"""

from typing import Optional, Dict, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User
from app.auth.dependencies import get_current_active_user, get_optional_user
from app.billing.usage import check_usage_limit
from app.workers.tasks import generate_cad_task, regenerate_cad_task, get_task_status
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class GenerateJobRequest(BaseModel):
    """Async generation job request."""
    prompt: str = Field(..., min_length=3, max_length=1000)
    backend: str = Field(default="build123d")


class RegenerateJobRequest(BaseModel):
    """Async regeneration job request."""
    feature_graph: dict
    prompt: str = Field(default="")


class JobResponse(BaseModel):
    """Job submission response."""
    job_id: str
    task_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    task_id: str
    status: str
    progress: Optional[int] = None
    stage: Optional[str] = None
    message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.post(
    "/generate",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start async CAD generation",
)
async def start_generation_job(
    request: GenerateJobRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start an asynchronous CAD generation job.

    Returns immediately with a job ID for status polling.
    Use GET /jobs/{job_id} to check progress.
    """
    # Check usage limit
    limit_check = await check_usage_limit(db, current_user.id)
    if not limit_check["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": limit_check.get("message", "Usage limit reached"),
                "code": limit_check.get("reason", "LIMIT_REACHED"),
                "used": limit_check.get("used"),
                "limit": limit_check.get("limit"),
            }
        )

    # Create job
    job_id = str(uuid.uuid4())

    # Submit to Celery queue
    task = generate_cad_task.delay(
        prompt=request.prompt,
        user_id=str(current_user.id),
        backend=request.backend,
        job_id=job_id,
    )

    logger.info(
        "generation_job_started",
        job_id=job_id,
        task_id=task.id,
        user_id=str(current_user.id),
    )

    return JobResponse(
        job_id=job_id,
        task_id=task.id,
        status="pending",
        message="Generation job started. Poll /jobs/{job_id} for status.",
    )


@router.post(
    "/regenerate",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start async CAD regeneration",
)
async def start_regeneration_job(
    request: RegenerateJobRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start an asynchronous CAD regeneration job from edited feature graph.

    Returns immediately with a job ID for status polling.
    """
    job_id = str(uuid.uuid4())

    # Submit to Celery queue
    task = regenerate_cad_task.delay(
        feature_graph=request.feature_graph,
        user_id=str(current_user.id),
        prompt=request.prompt,
        job_id=job_id,
    )

    logger.info(
        "regeneration_job_started",
        job_id=job_id,
        task_id=task.id,
        user_id=str(current_user.id),
    )

    return JobResponse(
        job_id=job_id,
        task_id=task.id,
        status="pending",
        message="Regeneration job started. Poll /jobs/{job_id} for status.",
    )


@router.get(
    "/{task_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
)
async def get_job_status(
    task_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Get the status of an async job.

    Returns:
    - pending: Job is waiting to be processed
    - processing: Job is being processed (includes progress %)
    - completed: Job finished successfully (includes result)
    - failed: Job failed (includes error message)
    """
    try:
        status_data = get_task_status(task_id)

        return JobStatusResponse(
            job_id=status_data.get("job_id", ""),
            task_id=task_id,
            status=status_data["status"],
            progress=status_data.get("progress"),
            stage=status_data.get("stage"),
            message=status_data.get("message"),
            result=status_data.get("result"),
            error=status_data.get("error"),
        )

    except Exception as e:
        logger.error(f"Failed to get job status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve job status"
        )


@router.delete(
    "/{task_id}",
    response_model=MessageResponse,
    summary="Cancel job",
)
async def cancel_job(
    task_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Attempt to cancel a running job.

    Note: Cancellation is not guaranteed if the task is already processing.
    """
    from celery.result import AsyncResult
    from app.workers.celery_app import celery_app

    try:
        result = AsyncResult(task_id, app=celery_app)

        if result.state in ["PENDING", "STARTED"]:
            result.revoke(terminate=True)
            logger.info(
                "job_cancelled",
                task_id=task_id,
                user_id=str(current_user.id),
            )
            return MessageResponse(message="Job cancellation requested")

        elif result.state in ["SUCCESS", "FAILURE"]:
            return MessageResponse(message="Job has already completed")

        else:
            return MessageResponse(message=f"Job is in state: {result.state}")

    except Exception as e:
        logger.error(f"Failed to cancel job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel job"
        )
