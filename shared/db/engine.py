"""
Async SQLAlchemy engine and session factory for Phoenix v2.

Uses DATABASE_URL from environment (postgresql+asyncpg).
Reference: ImplementationPlan.md M1.6.

Phase H1: Replaced NullPool with QueuePool for production. NullPool opens
a fresh TCP connection for every query (catastrophic under load).
QueuePool reuses connections across requests, with pool_pre_ping to
detect dead connections, and a 30s statement timeout to kill runaway
queries before they exhaust the pool.
"""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_DEFAULT_URL = "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader"


def get_database_url() -> str:
    return (
        os.environ.get("API_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or _DEFAULT_URL
    )


def get_engine(*, use_null_pool: bool = False):
    """Create async engine.

    Args:
        use_null_pool: If True, use NullPool (one connection per query).
            Required for Alembic migrations and one-shot scripts.
            Default False — uses QueuePool sized for production load.
    """
    pool_size = int(os.environ.get("DB_POOL_SIZE", "20"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    statement_timeout_ms = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))

    kwargs: dict = {
        "echo": os.environ.get("SQL_ECHO", "").lower() == "true",
        "connect_args": {
            "server_settings": {
                "statement_timeout": str(statement_timeout_ms),
                "application_name": "phoenix-api",
            },
            "command_timeout": 60,
        },
    }

    if use_null_pool:
        kwargs["poolclass"] = NullPool
    else:
        # asyncpg uses an internal pool by default; we configure SQLAlchemy's
        # AsyncAdaptedQueuePool by setting pool_size + max_overflow
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 3600  # Recycle connections every hour

    return create_async_engine(get_database_url(), **kwargs)


def get_session_factory(engine=None):
    """Session factory for dependency injection."""
    eng = engine or get_engine()
    return async_sessionmaker(
        eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# Module-level engine and session factory (lazy init if needed)
_engine = None
_session_factory = None


def get_engine_singleton():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def async_session() -> AsyncSession:
    """Return a new async session (caller must close)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory(get_engine_singleton())
    return _session_factory()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yield a session that is closed after use."""
    session = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
