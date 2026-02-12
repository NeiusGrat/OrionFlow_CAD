"""
Authentication API endpoints.

Endpoints:
- POST /signup - Register new user
- POST /login - Login and get tokens
- POST /logout - Invalidate tokens
- POST /refresh - Refresh access token
- POST /forgot-password - Request password reset
- POST /reset-password - Reset password with token
- POST /verify-email - Verify email address
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, UserStatus, UserRole, AuditLog, AuditAction
from app.auth.jwt import create_token_pair, verify_token, TokenPair
from app.auth.password import (
    hash_password,
    verify_password,
    check_password_strength,
    generate_password_reset_token,
    generate_verification_token,
)
from app.auth.dependencies import get_current_user
from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class SignupRequest(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2, max_length=100)


class LoginRequest(BaseModel):
    """Login request (alternative to OAuth2 form)."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token pair response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    """Forgot password request."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Password reset request."""
    token: str
    new_password: str = Field(..., min_length=8)


class VerifyEmailRequest(BaseModel):
    """Email verification request."""
    token: str


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class UserResponse(BaseModel):
    """User data response."""
    id: str
    email: str
    name: str
    role: str
    status: str
    email_verified: bool
    created_at: str


# =============================================================================
# Endpoints
# =============================================================================

@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def signup(
    request: SignupRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Register a new user account.

    - Creates user with pending verification status
    - Sends verification email
    - Returns access tokens
    """
    # Check password strength
    is_valid, error_msg = check_password_strength(request.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Check if email already exists
    result = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    # Create user
    verification_token = generate_verification_token()
    user = User(
        email=request.email.lower(),
        password_hash=hash_password(request.password),
        name=request.name,
        role=UserRole.USER,
        status=UserStatus.PENDING_VERIFICATION,
        email_verification_token=verification_token,
    )
    db.add(user)

    # Create audit log
    audit = AuditLog(
        user_id=user.id,
        action=AuditAction.SIGNUP,
        ip_address=client_request.client.host if client_request else None,
        details={"email": request.email},
    )
    db.add(audit)

    await db.commit()
    await db.refresh(user)

    # Send verification email (background task)
    # background_tasks.add_task(send_verification_email, user.email, verification_token)

    # Create tokens
    token_pair = create_token_pair(
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
    )

    logger.info("user_registered", user_id=str(user.id), email=user.email)

    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login to get access tokens",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Authenticate user and return access tokens.

    Accepts OAuth2 password flow for compatibility with OpenAPI.
    """
    # Find user by email
    result = await db.execute(
        select(User).where(User.email == form_data.username.lower())
    )
    user = result.scalar_one_or_none()

    # Verify credentials
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check account status
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been suspended"
        )

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)

    # Create audit log
    audit = AuditLog(
        user_id=user.id,
        action=AuditAction.LOGIN,
        ip_address=client_request.client.host if client_request else None,
        success=True,
    )
    db.add(audit)

    await db.commit()

    # Create tokens
    token_pair = create_token_pair(
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
    )

    logger.info("user_login", user_id=str(user.id))

    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout and invalidate tokens",
)
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Logout user and invalidate tokens.

    Note: Client should also delete stored tokens.
    """
    # In a production system, we'd add the token to a blacklist
    # For now, just log the event

    audit = AuditLog(
        user_id=current_user.id,
        action=AuditAction.LOGOUT,
        ip_address=client_request.client.host if client_request else None,
    )
    db.add(audit)
    await db.commit()

    logger.info("user_logout", user_id=str(current_user.id))

    return MessageResponse(message="Successfully logged out")


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Get new access token using refresh token.
    """
    # Verify refresh token
    payload = verify_token(request.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Get user
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(payload.sub))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Create new tokens
    token_pair = create_token_pair(
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
    )

    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
)
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Request password reset email.

    Always returns success to prevent email enumeration.
    """
    result = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    user = result.scalar_one_or_none()

    if user:
        # Generate reset token
        reset_token = generate_password_reset_token()
        user.password_reset_token = reset_token
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.commit()

        # Send reset email (background task)
        # background_tasks.add_task(send_password_reset_email, user.email, reset_token)

        logger.info("password_reset_requested", email=request.email)

    # Always return success to prevent enumeration
    return MessageResponse(
        message="If an account exists with this email, you will receive a password reset link"
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password with token",
)
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    client_request: Request = None,
):
    """
    Reset password using reset token.
    """
    # Check password strength
    is_valid, error_msg = check_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Find user by reset token
    result = await db.execute(
        select(User).where(User.password_reset_token == request.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    # Check token expiry
    if user.password_reset_expires < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )

    # Update password
    user.password_hash = hash_password(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None

    # Create audit log
    audit = AuditLog(
        user_id=user.id,
        action=AuditAction.PASSWORD_CHANGE,
        ip_address=client_request.client.host if client_request else None,
    )
    db.add(audit)

    await db.commit()

    logger.info("password_reset_completed", user_id=str(user.id))

    return MessageResponse(message="Password has been reset successfully")


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email address",
)
async def verify_email(
    request: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify email address using verification token.
    """
    result = await db.execute(
        select(User).where(User.email_verification_token == request.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token"
        )

    # Mark email as verified
    user.email_verified = True
    user.email_verification_token = None
    user.status = UserStatus.ACTIVE

    await db.commit()

    logger.info("email_verified", user_id=str(user.id))

    return MessageResponse(message="Email verified successfully")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """
    Get current authenticated user's profile.
    """
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        role=current_user.role.value,
        status=current_user.status.value,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at.isoformat(),
    )
