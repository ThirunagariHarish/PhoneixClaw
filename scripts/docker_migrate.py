"""Production DB initializer — creates all tables via SQLAlchemy metadata.

Used by the phoenix-db-migrate service in docker-compose.coolify.yml.
After create_all, applies V3 cleanup (drop VPS columns/tables).
"""
import asyncio
import os
import sys


CURRENT_MIGRATION = "09b0dd176f5d"

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
    "ALTER TABLE agent_backtests ADD COLUMN IF NOT EXISTS current_step VARCHAR(100)",
    "ALTER TABLE agent_backtests ADD COLUMN IF NOT EXISTS progress_pct INTEGER NOT NULL DEFAULT 0",
]

# Migrations 008-013: columns that create_all won't add to pre-existing tables
V4_ADD_COLUMNS_SQL = [
    "ALTER TABLE agent_trades ADD COLUMN IF NOT EXISTS decision_status VARCHAR(20) NOT NULL DEFAULT 'accepted'",
    "ALTER TABLE agent_trades ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
    "ALTER TABLE agent_backtests ADD COLUMN IF NOT EXISTS model_selection JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE agent_backtests ADD COLUMN IF NOT EXISTS backtesting_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS parent_agent_id UUID",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS position_ticker VARCHAR(20)",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS position_side VARCHAR(10)",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS session_role VARCHAR(30) NOT NULL DEFAULT 'primary'",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS host_name VARCHAR(100)",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS pid INTEGER",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) NOT NULL DEFAULT 'info'",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS channels_sent JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS pending_improvements JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_research_at TIMESTAMP WITH TIME ZONE",
]

# Migrations 014-09b0dd176f5d: columns added after initial V4 backfill
V5_ADD_COLUMNS_SQL = [
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS source VARCHAR(50) NOT NULL DEFAULT 'manual'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS channel_name VARCHAR(100)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS analyst_name VARCHAR(100)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS model_type VARCHAR(50)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS model_accuracy DOUBLE PRECISION",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS daily_pnl DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS total_pnl DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS total_trades INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS win_rate DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_signal_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_trade_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS manifest JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS current_mode VARCHAR(30) NOT NULL DEFAULT 'conservative'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS rules_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS runtime_status VARCHAR(16)",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS daily_token_budget_usd DOUBLE PRECISION",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS monthly_token_budget_usd DOUBLE PRECISION",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS tokens_used_today_usd DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS tokens_used_month_usd DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS budget_reset_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS auto_paused_reason VARCHAR(100)",
    "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS trading_mode VARCHAR(20) NOT NULL DEFAULT 'live'",
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

        for sql in V4_ADD_COLUMNS_SQL:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                print(f"  (skipped: {e})")
        print("V4 new columns ensured (migrations 008-013).")

        for sql in V5_ADD_COLUMNS_SQL:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                print(f"  (skipped: {e})")
        print("V5 new columns ensured (migrations 014-09b0dd176f5d).")

    # Seed reserved system-agent rows (idempotent) so FK in agent_sessions is satisfied.
    _SYSTEM_AGENTS = [
        ("00000000-0000-0000-0000-000000000001", "system", "Supervisor Agent"),
        ("00000000-0000-0000-0000-000000000002", "system", "Morning Briefing Agent"),
        ("00000000-0000-0000-0000-000000000003", "system", "EOD Analysis Agent"),
        ("00000000-0000-0000-0000-000000000004", "system", "Daily Summary Agent"),
        ("00000000-0000-0000-0000-000000000005", "system", "Trade Feedback Agent"),
    ]
    async with engine.begin() as conn:
        for uid, atype, name in _SYSTEM_AGENTS:
            try:
                await conn.execute(
                    text("""
                        INSERT INTO agents (id, name, type, status, config,
                                           worker_status, source,
                                           manifest, pending_improvements,
                                           current_mode, rules_version,
                                           daily_pnl, total_pnl, total_trades,
                                           win_rate, tokens_used_today_usd,
                                           tokens_used_month_usd)
                        VALUES (:id, :name, :type, 'SYSTEM', '{}',
                                'STOPPED', 'system',
                                '{}', '{}',
                                'conservative', 1,
                                0, 0, 0,
                                0, 0, 0)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {"id": uid, "name": name, "type": atype},
                )
            except Exception as e:
                print(f"  (seed agent {name} skipped: {e})")
    print("System agent rows seeded (idempotent).")

    await engine.dispose()
    print("DB tables ready.")


def main():
    asyncio.run(create_all_tables())


if __name__ == "__main__":
    main()
