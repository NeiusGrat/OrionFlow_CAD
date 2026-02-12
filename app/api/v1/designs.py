"""
Design management API endpoints.

Endpoints:
- GET / - List user's designs
- POST / - Create new design
- GET /{design_id} - Get design details
- PATCH /{design_id} - Update design
- DELETE /{design_id} - Delete design
- GET /{design_id}/history - Get generation history
"""

from typing import List, Optional
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models import User, Design, GenerationHistory, GenerationStatus
from app.auth.dependencies import get_current_active_user
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class CreateDesignRequest(BaseModel):
    """Create design request."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    prompt: str = Field(..., min_length=3)
    feature_graph: dict
    glb_path: Optional[str] = None
    step_path: Optional[str] = None
    stl_path: Optional[str] = None


class UpdateDesignRequest(BaseModel):
    """Update design request."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    feature_graph: Optional[dict] = None
    is_public: Optional[bool] = None
    tags: Optional[List[str]] = None


class DesignResponse(BaseModel):
    """Design response."""
    id: str
    name: str
    description: Optional[str]
    original_prompt: str
    feature_graph: dict
    glb_path: Optional[str]
    step_path: Optional[str]
    stl_path: Optional[str]
    is_public: bool
    tags: List[str]
    created_at: str
    updated_at: str


class DesignListResponse(BaseModel):
    """Paginated design list response."""
    items: List[DesignResponse]
    total: int
    page: int
    per_page: int
    pages: int


class GenerationHistoryResponse(BaseModel):
    """Generation history entry."""
    id: str
    prompt: str
    status: str
    error_message: Optional[str]
    duration_ms: Optional[int]
    created_at: str
    completed_at: Optional[str]


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get(
    "",
    response_model=DesignListResponse,
    summary="List user's designs",
)
async def list_designs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List designs for the current user.

    Supports pagination and search.
    """
    # Build query
    query = select(Design).where(Design.user_id == current_user.id)

    if search:
        query = query.where(
            Design.name.ilike(f"%{search}%") |
            Design.description.ilike(f"%{search}%")
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total = result.scalar()

    # Apply pagination
    query = query.order_by(Design.updated_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    designs = result.scalars().all()

    return DesignListResponse(
        items=[
            DesignResponse(
                id=str(d.id),
                name=d.name,
                description=d.description,
                original_prompt=d.original_prompt,
                feature_graph=d.feature_graph,
                glb_path=d.glb_path,
                step_path=d.step_path,
                stl_path=d.stl_path,
                is_public=d.is_public,
                tags=d.tags or [],
                created_at=d.created_at.isoformat(),
                updated_at=d.updated_at.isoformat(),
            )
            for d in designs
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.post(
    "",
    response_model=DesignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new design",
)
async def create_design(
    request: CreateDesignRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save a generated design to the user's library.
    """
    design = Design(
        user_id=current_user.id,
        name=request.name,
        description=request.description,
        original_prompt=request.prompt,
        feature_graph=request.feature_graph,
        glb_path=request.glb_path,
        step_path=request.step_path,
        stl_path=request.stl_path,
    )
    db.add(design)
    await db.commit()
    await db.refresh(design)

    logger.info(
        "design_created",
        user_id=str(current_user.id),
        design_id=str(design.id),
    )

    return DesignResponse(
        id=str(design.id),
        name=design.name,
        description=design.description,
        original_prompt=design.original_prompt,
        feature_graph=design.feature_graph,
        glb_path=design.glb_path,
        step_path=design.step_path,
        stl_path=design.stl_path,
        is_public=design.is_public,
        tags=design.tags or [],
        created_at=design.created_at.isoformat(),
        updated_at=design.updated_at.isoformat(),
    )


@router.get(
    "/{design_id}",
    response_model=DesignResponse,
    summary="Get design details",
)
async def get_design(
    design_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a specific design.
    """
    try:
        design_uuid = uuid.UUID(design_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid design ID"
        )

    result = await db.execute(
        select(Design).where(
            Design.id == design_uuid,
            Design.user_id == current_user.id,
        )
    )
    design = result.scalar_one_or_none()

    if not design:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Design not found"
        )

    return DesignResponse(
        id=str(design.id),
        name=design.name,
        description=design.description,
        original_prompt=design.original_prompt,
        feature_graph=design.feature_graph,
        glb_path=design.glb_path,
        step_path=design.step_path,
        stl_path=design.stl_path,
        is_public=design.is_public,
        tags=design.tags or [],
        created_at=design.created_at.isoformat(),
        updated_at=design.updated_at.isoformat(),
    )


@router.patch(
    "/{design_id}",
    response_model=DesignResponse,
    summary="Update design",
)
async def update_design(
    design_id: str,
    request: UpdateDesignRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a design's metadata or feature graph.
    """
    try:
        design_uuid = uuid.UUID(design_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid design ID"
        )

    result = await db.execute(
        select(Design).where(
            Design.id == design_uuid,
            Design.user_id == current_user.id,
        )
    )
    design = result.scalar_one_or_none()

    if not design:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Design not found"
        )

    # Update fields
    if request.name is not None:
        design.name = request.name
    if request.description is not None:
        design.description = request.description
    if request.feature_graph is not None:
        design.feature_graph = request.feature_graph
    if request.is_public is not None:
        design.is_public = request.is_public
    if request.tags is not None:
        design.tags = request.tags

    await db.commit()
    await db.refresh(design)

    logger.info(
        "design_updated",
        user_id=str(current_user.id),
        design_id=str(design.id),
    )

    return DesignResponse(
        id=str(design.id),
        name=design.name,
        description=design.description,
        original_prompt=design.original_prompt,
        feature_graph=design.feature_graph,
        glb_path=design.glb_path,
        step_path=design.step_path,
        stl_path=design.stl_path,
        is_public=design.is_public,
        tags=design.tags or [],
        created_at=design.created_at.isoformat(),
        updated_at=design.updated_at.isoformat(),
    )


@router.delete(
    "/{design_id}",
    response_model=MessageResponse,
    summary="Delete design",
)
async def delete_design(
    design_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a design and its associated files.
    """
    try:
        design_uuid = uuid.UUID(design_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid design ID"
        )

    result = await db.execute(
        select(Design).where(
            Design.id == design_uuid,
            Design.user_id == current_user.id,
        )
    )
    design = result.scalar_one_or_none()

    if not design:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Design not found"
        )

    # TODO: Delete associated files from storage

    await db.delete(design)
    await db.commit()

    logger.info(
        "design_deleted",
        user_id=str(current_user.id),
        design_id=design_id,
    )

    return MessageResponse(message="Design deleted successfully")


@router.get(
    "/{design_id}/history",
    response_model=List[GenerationHistoryResponse],
    summary="Get generation history",
)
async def get_generation_history(
    design_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get generation history for a design.
    """
    try:
        design_uuid = uuid.UUID(design_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid design ID"
        )

    # Verify design ownership
    result = await db.execute(
        select(Design).where(
            Design.id == design_uuid,
            Design.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Design not found"
        )

    # Get history
    result = await db.execute(
        select(GenerationHistory)
        .where(GenerationHistory.design_id == design_uuid)
        .order_by(GenerationHistory.created_at.desc())
    )
    history = result.scalars().all()

    return [
        GenerationHistoryResponse(
            id=str(h.id),
            prompt=h.prompt,
            status=h.status.value,
            error_message=h.error_message,
            duration_ms=h.duration_ms,
            created_at=h.created_at.isoformat(),
            completed_at=h.completed_at.isoformat() if h.completed_at else None,
        )
        for h in history
    ]
