"""
JWT token management for OrionFlow.

Handles:
- Access token generation (short-lived, 15 min default)
- Refresh token generation (long-lived, 7 days default)
- Token verification and decoding
- Token blacklisting for logout
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import uuid

from jose import jwt, JWTError
from pydantic import BaseModel

from app.config import settings


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # User ID
    email: str
    role: str
    exp: datetime
    iat: datetime
    jti: str  # Token ID for blacklisting
    type: str  # "access" or "refresh"


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def create_access_token(
    user_id: str,
    email: str,
    role: str = "user",
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role (user, admin, developer)
        expires_delta: Token expiration time (default: 15 minutes)

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
        "iat": now,
        "jti": str(uuid.uuid4()),
        "type": "access",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )


def create_refresh_token(
    user_id: str,
    email: str,
    role: str = "user",
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token.

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role
        expires_delta: Token expiration time (default: 7 days)

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)

    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
        "iat": now,
        "jti": str(uuid.uuid4()),
        "type": "refresh",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )


def create_token_pair(
    user_id: str,
    email: str,
    role: str = "user"
) -> TokenPair:
    """
    Create both access and refresh tokens.

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role

    Returns:
        TokenPair with access and refresh tokens
    """
    access_token = create_access_token(user_id, email, role)
    refresh_token = create_refresh_token(user_id, email, role)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60
    )


def verify_token(token: str, token_type: str = "access") -> Optional[TokenPayload]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token string
        token_type: Expected token type ("access" or "refresh")

    Returns:
        TokenPayload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )

        # Verify token type
        if payload.get("type") != token_type:
            return None

        return TokenPayload(**payload)

    except JWTError:
        return None


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode a JWT token without verification.

    Useful for debugging or extracting claims from expired tokens.

    Args:
        token: JWT token string

    Returns:
        Token payload dict or None
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False}
        )
    except JWTError:
        return None


def get_token_id(token: str) -> Optional[str]:
    """
    Extract the token ID (jti) from a token.

    Used for blacklisting tokens on logout.

    Args:
        token: JWT token string

    Returns:
        Token ID (jti) or None
    """
    payload = decode_token(token)
    return payload.get("jti") if payload else None
