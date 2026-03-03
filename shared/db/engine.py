"""
Async SQLAlchemy engine and session factory for Phoenix v2.

Uses DATABASE_URL from environment (postgresql+asyncpg).
Reference: ImplementationPlan.md M1.6.
"""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_DEFAULT_URL = "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader"

def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def get_engine():
    """Create async engine. Use NullPool for migrations."""
    return create_async_engine(
        get_database_url(),
        echo=os.environ.get("SQL_ECHO", "").lower() == "true",
        poolclass=NullPool,
    )


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
