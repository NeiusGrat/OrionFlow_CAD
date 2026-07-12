"""
Password hashing and verification for OrionFlow.

Uses bcrypt for secure password hashing with:
- Automatic salt generation
- Configurable work factor
- Timing-safe comparison
"""

import secrets
from typing import Tuple

import bcrypt

# passlib was dropped: it is unmaintained and its bcrypt backend self-test
# crashes with bcrypt>=4.1 ("password cannot be longer than 72 bytes").
# Hashes produced by passlib ($2b$...) verify fine with bcrypt directly.

_BCRYPT_ROUNDS = 12  # Work factor (2^12 iterations)


def _to_bcrypt_secret(value: str) -> bytes:
    # bcrypt only reads the first 72 bytes; newer versions raise instead of
    # truncating silently, so truncate explicitly.
    return value.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return bcrypt.hashpw(
        _to_bcrypt_secret(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Uses timing-safe comparison to prevent timing attacks.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(
            _to_bcrypt_secret(plain_password), hashed_password.encode("utf-8")
        )
    except ValueError:
        # Malformed / non-bcrypt hash in storage
        return False


def generate_password_reset_token() -> str:
    """
    Generate a secure random token for password reset.

    Returns:
        URL-safe random token string (32 bytes / 43 chars)
    """
    return secrets.token_urlsafe(32)


def generate_verification_token() -> str:
    """
    Generate a secure random token for email verification.

    Returns:
        URL-safe random token string (32 bytes / 43 chars)
    """
    return secrets.token_urlsafe(32)


def generate_api_key() -> Tuple[str, str]:
    """
    Generate a new API key.

    Returns:
        Tuple of (full key, key prefix for identification)
    """
    # Generate a secure random key
    key = f"of_{secrets.token_urlsafe(32)}"  # "of_" prefix for OrionFlow
    prefix = key[:10]  # First 10 chars for identification

    return key, prefix


def hash_api_key(key: str) -> str:
    """
    Hash an API key for storage.

    Args:
        key: Full API key

    Returns:
        Hashed key for storage
    """
    return hash_password(key)


def verify_api_key(key: str, hashed_key: str) -> bool:
    """
    Verify an API key against its hash.

    Args:
        key: Full API key to verify
        hashed_key: Stored hash

    Returns:
        True if key matches, False otherwise
    """
    return verify_password(key, hashed_key)


def check_password_strength(password: str) -> Tuple[bool, str]:
    """
    Check if password meets minimum security requirements.

    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character

    Args:
        password: Password to check

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"

    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        return False, "Password must contain at least one special character"

    return True, ""
