"""
Database session management with connection pooling.

Provides async SQLAlchemy engine and session factories with:
- Connection pooling for production workloads
- Health check endpoints
- Graceful shutdown handling
"""

from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text

from app.config import settings


def get_database_url() -> str:
    """Build database URL from settings."""
    from urllib.parse import quote_plus

    return (
        f"postgresql+asyncpg://{quote_plus(settings.db_user)}:"
        f"{quote_plus(settings.db_password)}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def create_engine() -> AsyncEngine:
    """
    Create async SQLAlchemy engine with connection pooling.

    Pool configuration:
    - pool_size: 5 (base connections kept open)
    - max_overflow: 10 (extra connections when pool exhausted)
    - pool_timeout: 30 (seconds to wait for connection)
    - pool_recycle: 1800 (recycle connections after 30 min)
    """
    pool_class = NullPool if settings.testing else AsyncAdaptedQueuePool

    connect_args: dict = {
        # asyncpg defaults to a 60s connect timeout; a down DB would stall
        # startup and every auth request for a minute.
        "timeout": 10,
    }
    if settings.db_ssl:
        import ssl as ssl_module

        # Supabase poolers present a cert from Supabase's own CA, which is not
        # in system trust stores — encrypt without chain verification.
        ctx = ssl_module.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_NONE
        connect_args["ssl"] = ctx
        # Supabase/Neon poolers break asyncpg's prepared-statement cache.
        connect_args["statement_cache_size"] = 0

    engine_kwargs = {
        "echo": settings.db_echo,
        "pool_pre_ping": True,  # Verify connections before use
        "connect_args": connect_args,
    }

    if not settings.testing:
        engine_kwargs.update(
            {
                "poolclass": pool_class,
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": 30,
                "pool_recycle": 1800,
            }
        )

    return create_async_engine(get_database_url(), **engine_kwargs)


# Global engine instance
async_engine = create_engine()

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.

    Usage:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions outside of FastAPI.

    Usage:
        async with get_db_context() as db:
            user = await db.get(User, user_id)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.

    Called on application startup to ensure tables exist.
    For production, use Alembic migrations instead.
    """
    from app.db.models import Base

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close database connections gracefully.

    Called on application shutdown.
    """
    await async_engine.dispose()


async def check_db_health() -> bool:
    """
    Check database connectivity.

    Returns:
        True if database is reachable, False otherwise
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception:
        return False
