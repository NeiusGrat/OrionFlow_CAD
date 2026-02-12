"""
Rate limiting middleware for OrionFlow.

Uses Redis for distributed rate limiting with:
- Per-IP rate limits
- Per-user rate limits
- Per-API-key rate limits
- Sliding window algorithm
"""

from typing import Optional, Callable
from datetime import datetime, timezone
import time

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_identifier(request: Request) -> str:
    """
    Get rate limit identifier from request.

    Priority:
    1. API key (X-API-Key header)
    2. User ID (from JWT token)
    3. IP address

    Args:
        request: FastAPI request

    Returns:
        Identifier string for rate limiting
    """
    # Try API key first
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api_key:{api_key[:10]}"

    # Try user ID from JWT
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            from app.auth.jwt import decode_token
            payload = decode_token(token)
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"
        except Exception:
            pass

    # Fall back to IP address
    return f"ip:{get_remote_address(request)}"


# Create limiter instance
limiter = Limiter(
    key_func=get_identifier,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url if settings.redis_url else None,
    strategy="fixed-window",
)


def get_rate_limiter() -> Limiter:
    """Get the rate limiter instance."""
    return limiter


def rate_limit(limit: str):
    """
    Decorator for custom rate limits on specific endpoints.

    Usage:
        @app.post("/generate")
        @rate_limit("10/minute")
        async def generate_cad(request: Request):
            ...

    Args:
        limit: Rate limit string (e.g., "10/minute", "100/hour")

    Returns:
        Decorator function
    """
    return limiter.limit(limit)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with Redis support.

    Features:
    - Configurable limits per endpoint
    - User and API key aware
    - Graceful degradation without Redis
    """

    async def dispatch(self, request: Request, call_next):
        """Process request through rate limiter."""
        # Skip rate limiting for health checks and docs
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        try:
            # Apply rate limit
            response = await call_next(request)

            # Add rate limit headers
            identifier = get_identifier(request)
            # Headers would be added by slowapi limiter

            return response

        except RateLimitExceeded as e:
            logger.warning(
                "rate_limit_exceeded",
                identifier=get_identifier(request),
                path=request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": getattr(e, "retry_after", 60),
                }
            )


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter using Redis.

    More accurate than fixed window for preventing bursts.
    """

    def __init__(self, redis_client, window_size: int = 60, max_requests: int = 60):
        """
        Initialize rate limiter.

        Args:
            redis_client: Redis client instance
            window_size: Window size in seconds
            max_requests: Maximum requests per window
        """
        self.redis = redis_client
        self.window_size = window_size
        self.max_requests = max_requests

    async def is_allowed(self, identifier: str) -> tuple[bool, dict]:
        """
        Check if request is allowed.

        Args:
            identifier: Rate limit identifier

        Returns:
            Tuple of (is_allowed, metadata)
        """
        if not self.redis:
            return True, {"remaining": -1}

        key = f"rate_limit:{identifier}"
        now = time.time()
        window_start = now - self.window_size

        try:
            pipe = self.redis.pipeline()

            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)

            # Count current entries
            pipe.zcard(key)

            # Add current request
            pipe.zadd(key, {str(now): now})

            # Set expiry
            pipe.expire(key, self.window_size)

            results = await pipe.execute()
            current_count = results[1]

            remaining = max(0, self.max_requests - current_count - 1)
            is_allowed = current_count < self.max_requests

            return is_allowed, {
                "remaining": remaining,
                "limit": self.max_requests,
                "reset": int(now + self.window_size),
            }

        except Exception as e:
            logger.error("rate_limit_redis_error", error=str(e))
            # Fail open - allow request if Redis is down
            return True, {"remaining": -1}

    async def get_usage(self, identifier: str) -> dict:
        """
        Get current usage for identifier.

        Args:
            identifier: Rate limit identifier

        Returns:
            Usage statistics
        """
        if not self.redis:
            return {"count": 0, "limit": self.max_requests}

        key = f"rate_limit:{identifier}"
        now = time.time()
        window_start = now - self.window_size

        try:
            # Remove old and count current
            await self.redis.zremrangebyscore(key, 0, window_start)
            count = await self.redis.zcard(key)

            return {
                "count": count,
                "limit": self.max_requests,
                "remaining": max(0, self.max_requests - count),
                "window_size": self.window_size,
            }

        except Exception as e:
            logger.error("rate_limit_usage_error", error=str(e))
            return {"count": 0, "limit": self.max_requests}
