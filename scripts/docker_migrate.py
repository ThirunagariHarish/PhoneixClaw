"""Production DB initializer — creates all tables via SQLAlchemy metadata.

Used by the phoenix-db-migrate service in docker-compose.coolify.yml.
After create_all, applies V3 cleanup (drop VPS columns/tables).
"""
import asyncio
import os
import sys


CURRENT_MIGRATION = "007"

V3_CLEANUP_SQL = [
    "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_instance_id_fkey",
    "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_backtest_instance_id_fkey",
    "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_trading_instance_id_fkey",
    "ALTER TABLE agents DROP COLUMN IF EXISTS instance_id",
    "ALTER TABLE agents DROP COLUMN IF EXISTS backtest_instance_id",
    "ALTER TABLE agents DROP COLUMN IF EXISTS trading_instance_id",
    "DROP TABLE IF EXISTS claude_code_instances",
]

V3_ADD_COLUMNS_SQL = [
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS phoenix_api_key VARCHAR(200)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS worker_container_id VARCHAR(100)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS worker_status VARCHAR(30) NOT NULL DEFAULT 'STOPPED'",
]


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
                text(f"INSERT INTO alembic_version VALUES ('{CURRENT_MIGRATION}')")
            )
            print(f"Stamped alembic_version at {CURRENT_MIGRATION}")
        else:
            await conn.execute(
                text(f"UPDATE alembic_version SET version_num = '{CURRENT_MIGRATION}'")
            )
            print(f"Updated alembic_version to {CURRENT_MIGRATION}")

        for sql in V3_CLEANUP_SQL:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                print(f"  (skipped: {e})")
        print("V3 cleanup complete — VPS columns and tables removed.")

        for sql in V3_ADD_COLUMNS_SQL:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                print(f"  (skipped: {e})")
        print("V3 new columns ensured.")

    await engine.dispose()
    print("DB tables ready.")


def main():
    asyncio.run(create_all_tables())


if __name__ == "__main__":
    main()
