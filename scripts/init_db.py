"""Create all Phoenix v2 database tables."""

import asyncio

from shared.db.engine import get_engine
from shared.db.models import Base  # noqa: F401 — registers all models


async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("  Database tables created.")


if __name__ == "__main__":
    asyncio.run(main())
