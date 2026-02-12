"""
Authentication module for OrionFlow.

Provides:
- JWT token generation and validation
- Password hashing with bcrypt
- OAuth2 authentication flows
- API key authentication
"""

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    verify_token,
    decode_token,
    TokenPayload,
)
from app.auth.password import (
    hash_password,
    verify_password,
    generate_password_reset_token,
)
from app.auth.dependencies import (
    get_current_user,
    get_current_active_user,
    get_current_admin_user,
    get_optional_user,
    get_api_key,
)

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "decode_token",
    "TokenPayload",
    "hash_password",
    "verify_password",
    "generate_password_reset_token",
    "get_current_user",
    "get_current_active_user",
    "get_current_admin_user",
    "get_optional_user",
    "get_api_key",
]
