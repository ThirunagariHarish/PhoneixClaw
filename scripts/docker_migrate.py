"""Production DB initializer — creates all tables via SQLAlchemy metadata.

Used by the phoenix-db-migrate service in docker-compose.coolify.yml.
Falls back from alembic to raw create_all if migrations fail.
"""
import asyncio
import os
import subprocess
import sys


async def create_all_tables():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from shared.db.models import Base  # registers all models

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        row = await conn.execute(
            text(
                "SELECT EXISTS("
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name='alembic_version')"
            )
        )
        if not row.scalar():
            await conn.execute(
                text(
                    "CREATE TABLE alembic_version "
                    "(version_num VARCHAR(32) NOT NULL)"
                )
            )
            await conn.execute(
                text("INSERT INTO alembic_version VALUES ('006')")
            )
            print("Stamped alembic_version at 006")

    await engine.dispose()
    print("DB tables ready.")


def main():
    asyncio.run(create_all_tables())


if __name__ == "__main__":
    main()
