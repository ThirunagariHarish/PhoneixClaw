from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config.base_config import config

_engine_kwargs: dict = {"echo": False}
if "sqlite" not in config.database.url:
    _engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)

engine = create_async_engine(config.database.url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with AsyncSessionLocal() as session:
        yield session


async_session_factory = AsyncSessionLocal


async def init_db() -> None:
    from shared.models.trade import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE board_tasks ADD COLUMN IF NOT EXISTS labels JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE board_tasks ADD COLUMN IF NOT EXISTS due_date TIMESTAMPTZ"
        ))
