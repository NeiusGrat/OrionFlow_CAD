"""
FastAPI authentication dependencies for OrionFlow.

Provides:
- JWT token authentication
- API key authentication
- Role-based access control
"""

from typing import Optional
import uuid

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.session import get_db
from app.db.models import User, APIKey, UserStatus, UserRole
from app.auth.jwt import verify_token, TokenPayload
from app.auth.password import verify_api_key


# OAuth2 scheme for JWT authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False
)

# API key header scheme
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False
)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> User:
    """
    Get the current authenticated user.

    Supports both JWT tokens and API keys.

    Args:
        db: Database session
        token: JWT access token (from Authorization header)
        api_key: API key (from X-API-Key header)

    Returns:
        Authenticated User object

    Raises:
        HTTPException: If authentication fails
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try JWT authentication first
    if token:
        payload = verify_token(token, token_type="access")
        if payload is None:
            raise credentials_exception

        # Get user from database
        try:
            user_id = uuid.UUID(payload.sub)
        except ValueError:
            raise credentials_exception

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if user is None:
            raise credentials_exception

        return user

    # Try API key authentication
    if api_key:
        return await get_api_key_user(db, api_key)

    raise credentials_exception


async def get_api_key_user(db: AsyncSession, key: str) -> User:
    """
    Authenticate using an API key.

    Args:
        db: Database session
        key: Full API key

    Returns:
        User associated with the API key

    Raises:
        HTTPException: If API key is invalid
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Extract prefix for lookup
    prefix = key[:10] if len(key) >= 10 else key

    # Find API keys with matching prefix
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_prefix == prefix,
            APIKey.is_active == True
        )
    )
    api_keys = result.scalars().all()

    # Verify the full key
    for api_key in api_keys:
        if verify_api_key(key, api_key.key_hash):
            # Update last used timestamp
            from datetime import datetime, timezone
            api_key.last_used_at = datetime.now(timezone.utc)
            api_key.usage_count += 1
            await db.commit()

            # Get associated user
            result = await db.execute(
                select(User).where(User.id == api_key.user_id)
            )
            user = result.scalar_one_or_none()

            if user is None:
                raise credentials_exception

            return user

    raise credentials_exception


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get the current active (non-suspended) user.

    Args:
        current_user: Current authenticated user

    Returns:
        Active User object

    Raises:
        HTTPException: If user is not active
    """
    if current_user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active"
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get the current user if they have admin role.

    Args:
        current_user: Current active user

    Returns:
        Admin User object

    Raises:
        HTTPException: If user is not an admin
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return current_user


async def get_optional_user(
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
) -> Optional[User]:
    """
    Get the current user if authenticated, None otherwise.

    Useful for endpoints that work with or without authentication
    but provide enhanced functionality for authenticated users.

    Args:
        db: Database session
        token: JWT access token
        api_key: API key

    Returns:
        User object if authenticated, None otherwise
    """
    if not token and not api_key:
        return None

    try:
        return await get_current_user(db, token, api_key)
    except HTTPException:
        return None


def require_scope(required_scope: str):
    """
    Dependency factory for API key scope checking.

    Usage:
        @app.get("/admin/users")
        async def get_users(
            user: User = Depends(require_scope("admin:read"))
        ):
            ...
    """
    async def scope_checker(
        db: AsyncSession = Depends(get_db),
        api_key: Optional[str] = Depends(api_key_header),
        current_user: User = Depends(get_current_user),
    ) -> User:
        # If using API key, check scope
        if api_key:
            prefix = api_key[:10] if len(api_key) >= 10 else api_key
            result = await db.execute(
                select(APIKey).where(
                    APIKey.key_prefix == prefix,
                    APIKey.is_active == True
                )
            )
            api_key_obj = result.scalar_one_or_none()

            if api_key_obj and required_scope not in api_key_obj.scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"API key missing required scope: {required_scope}"
                )

        return current_user

    return scope_checker


async def get_api_key(
    db: AsyncSession = Depends(get_db),
    api_key: Optional[str] = Depends(api_key_header),
) -> Optional[APIKey]:
    """
    Get the API key object if provided.

    Args:
        db: Database session
        api_key: API key from header

    Returns:
        APIKey object if valid, None otherwise
    """
    if not api_key:
        return None

    prefix = api_key[:10] if len(api_key) >= 10 else api_key

    result = await db.execute(
        select(APIKey).where(
            APIKey.key_prefix == prefix,
            APIKey.is_active == True
        )
    )
    api_keys = result.scalars().all()

    for key_obj in api_keys:
        if verify_api_key(api_key, key_obj.key_hash):
            return key_obj

    return None
