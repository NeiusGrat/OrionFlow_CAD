"""
User management API endpoints.

Endpoints:
- GET /me - Get current user profile
- PATCH /me - Update profile
- DELETE /me - Delete account
- GET /me/api-keys - List API keys
- POST /me/api-keys - Create API key
- DELETE /me/api-keys/{key_id} - Revoke API key
"""

from typing import List, Optional
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, APIKey, AuditLog, AuditAction
from app.auth.dependencies import get_current_user, get_current_active_user
from app.auth.password import generate_api_key, hash_api_key
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class UpdateProfileRequest(BaseModel):
    """Profile update request."""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    company: Optional[str] = Field(None, max_length=255)
    avatar_url: Optional[str] = Field(None, max_length=500)


class UserProfileResponse(BaseModel):
    """User profile response."""
    id: str
    email: str
    name: str
    company: Optional[str]
    avatar_url: Optional[str]
    role: str
    status: str
    email_verified: bool
    created_at: str
    last_login_at: Optional[str]


class CreateAPIKeyRequest(BaseModel):
    """API key creation request."""
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default=["read", "write"])


class APIKeyResponse(BaseModel):
    """API key response (without full key)."""
    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    created_at: str
    last_used_at: Optional[str]


class APIKeyCreatedResponse(BaseModel):
    """Response when API key is created (includes full key)."""
    id: str
    name: str
    key: str  # Full key - only returned once
    key_prefix: str
    scopes: List[str]
    created_at: str


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# =============================================================================
# Profile Endpoints
# =============================================================================

@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile",
)
async def get_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed profile for the current authenticated user.
    """
    return UserProfileResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        company=current_user.company,
        avatar_url=current_user.avatar_url,
        role=current_user.role.value,
        status=current_user.status.value,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at.isoformat(),
        last_login_at=current_user.last_login_at.isoformat() if current_user.last_login_at else None,
    )


@router.patch(
    "/me",
    response_model=UserProfileResponse,
    summary="Update current user profile",
)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update profile for the current authenticated user.
    """
    # Update only provided fields
    if request.name is not None:
        current_user.name = request.name
    if request.company is not None:
        current_user.company = request.company
    if request.avatar_url is not None:
        current_user.avatar_url = request.avatar_url

    await db.commit()
    await db.refresh(current_user)

    logger.info("profile_updated", user_id=str(current_user.id))

    return UserProfileResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        company=current_user.company,
        avatar_url=current_user.avatar_url,
        role=current_user.role.value,
        status=current_user.status.value,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at.isoformat(),
        last_login_at=current_user.last_login_at.isoformat() if current_user.last_login_at else None,
    )


@router.delete(
    "/me",
    response_model=MessageResponse,
    summary="Delete current user account",
)
async def delete_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Delete the current user's account.

    This action is irreversible and will:
    - Delete all user data
    - Cancel any active subscriptions
    - Remove all API keys
    """
    # Cancel subscription if exists
    if current_user.subscription:
        from app.billing.stripe_service import cancel_subscription
        try:
            await cancel_subscription(db, current_user, at_period_end=False)
        except Exception as e:
            logger.warning(f"Failed to cancel subscription: {e}")

    # Create audit log before deletion
    audit = AuditLog(
        user_id=current_user.id,
        action=AuditAction.LOGOUT,  # Account deletion
        ip_address=client_request.client.host if client_request else None,
        details={"action": "account_deleted"},
    )
    db.add(audit)

    # Delete user (cascade will handle related records)
    await db.delete(current_user)
    await db.commit()

    logger.info("account_deleted", user_id=str(current_user.id))

    return MessageResponse(message="Account deleted successfully")


# =============================================================================
# API Key Endpoints
# =============================================================================

@router.get(
    "/me/api-keys",
    response_model=List[APIKeyResponse],
    summary="List API keys",
)
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all API keys for the current user.
    """
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == current_user.id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [
        APIKeyResponse(
            id=str(key.id),
            name=key.name,
            key_prefix=key.key_prefix,
            scopes=key.scopes,
            is_active=key.is_active,
            created_at=key.created_at.isoformat(),
            last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
        )
        for key in keys
    ]


@router.post(
    "/me/api-keys",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new API key",
)
async def create_api_key_endpoint(
    request: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Create a new API key.

    **Important**: The full key is only returned once. Store it securely.
    """
    # Generate key
    full_key, prefix = generate_api_key()
    key_hash = hash_api_key(full_key)

    # Create API key record
    api_key = APIKey(
        user_id=current_user.id,
        name=request.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=request.scopes,
    )
    db.add(api_key)

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action=AuditAction.API_KEY_CREATE,
        resource_type="api_key",
        resource_id=str(api_key.id),
        ip_address=client_request.client.host if client_request else None,
        details={"name": request.name},
    )
    db.add(audit)

    await db.commit()
    await db.refresh(api_key)

    logger.info(
        "api_key_created",
        user_id=str(current_user.id),
        key_id=str(api_key.id),
    )

    return APIKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=full_key,  # Only returned once!
        key_prefix=api_key.key_prefix,
        scopes=api_key.scopes,
        created_at=api_key.created_at.isoformat(),
    )


@router.delete(
    "/me/api-keys/{key_id}",
    response_model=MessageResponse,
    summary="Revoke API key",
)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Revoke (deactivate) an API key.
    """
    try:
        key_uuid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid key ID"
        )

    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_uuid,
            APIKey.user_id == current_user.id,
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    # Deactivate rather than delete (for audit purposes)
    api_key.is_active = False

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action=AuditAction.API_KEY_REVOKE,
        resource_type="api_key",
        resource_id=str(api_key.id),
        ip_address=client_request.client.host if client_request else None,
    )
    db.add(audit)

    await db.commit()

    logger.info(
        "api_key_revoked",
        user_id=str(current_user.id),
        key_id=str(api_key.id),
    )

    return MessageResponse(message="API key revoked successfully")
