"""Create all Phoenix v2 database tables + ensure critical columns/tables exist.

This script runs on every container start (via entrypoint.sh) and is designed
to self-heal schema drift when Alembic migrations fail to apply (which has
happened in production). Every statement uses IF NOT EXISTS / IF EXISTS so
this is safe to run repeatedly and safe to run alongside Alembic.

What it guarantees:
  1. All tables from SQLAlchemy models exist (Base.metadata.create_all)
  2. Recent migration columns exist on agents (last_activity_at, runtime_status,
     budget columns, etc.)
  3. Phase P + T support tables exist (agent_logs, agent_crons, briefing_history,
     order_attempts, trade_outcomes_feedback)
"""

import asyncio

from sqlalchemy import text

from shared.db.engine import get_engine
from shared.db.models import Base  # noqa: F401 — registers all models


# Each entry: (table, column_name, column_definition) — added via ALTER IF NOT EXISTS
COLUMN_ENSURE = [
    # Phase H7 — token budget enforcement (migration 016)
    ("agents", "daily_token_budget_usd", "DOUBLE PRECISION"),
    ("agents", "monthly_token_budget_usd", "DOUBLE PRECISION"),
    ("agents", "tokens_used_today_usd", "DOUBLE PRECISION NOT NULL DEFAULT 0.0"),
    ("agents", "tokens_used_month_usd", "DOUBLE PRECISION NOT NULL DEFAULT 0.0"),
    ("agents", "budget_reset_at", "TIMESTAMPTZ"),
    ("agents", "auto_paused_reason", "VARCHAR(100)"),
    # Phase P — runtime status + heartbeat activity marker (migration 027)
    ("agents", "runtime_status", "VARCHAR(16)"),
    ("agents", "last_activity_at", "TIMESTAMPTZ"),
    # Migration 034 — trade_signals analyst columns
    # Missing on databases deployed before 034 ran; causes 500 ProgrammingError
    # on any INSERT/SELECT of the trade_signals table.
    ("trade_signals", "analyst_persona", "VARCHAR(50)"),
    ("trade_signals", "tool_signals_used", "JSONB"),
    ("trade_signals", "risk_reward_ratio", "DOUBLE PRECISION"),
    ("trade_signals", "take_profit", "DOUBLE PRECISION"),
    ("trade_signals", "entry_price", "DOUBLE PRECISION"),
    ("trade_signals", "stop_loss", "DOUBLE PRECISION"),
    ("trade_signals", "pattern_name", "VARCHAR(100)"),
    # connector_agents.is_active: NULL rows break is_active.is_(True) filter
    ("connector_agents", "is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
]


# Each entry: (table_name, create_sql) — only runs if table missing
TABLE_ENSURE = [
    (
        "agent_logs",
        """
        CREATE TABLE IF NOT EXISTS agent_logs (
            id BIGSERIAL PRIMARY KEY,
            agent_id VARCHAR(64) NOT NULL,
            level VARCHAR(16) NOT NULL DEFAULT 'info',
            source VARCHAR(64),
            message TEXT NOT NULL,
            context JSON,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_agent_logs_agent_time
            ON agent_logs (agent_id, created_at);
        """,
    ),
    (
        "agent_crons",
        """
        CREATE TABLE IF NOT EXISTS agent_crons (
            id VARCHAR(64) PRIMARY KEY,
            agent_id VARCHAR(64) NOT NULL,
            name VARCHAR(128) NOT NULL,
            cron_expression VARCHAR(64) NOT NULL,
            action_type VARCHAR(64) NOT NULL DEFAULT 'prompt',
            action_payload JSON,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_run_at TIMESTAMPTZ,
            next_run_at TIMESTAMPTZ,
            run_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_agent_crons_agent
            ON agent_crons (agent_id);
        """,
    ),
    (
        "briefing_history",
        """
        CREATE TABLE IF NOT EXISTS briefing_history (
            id BIGSERIAL PRIMARY KEY,
            kind VARCHAR(32) NOT NULL DEFAULT 'morning',
            agent_session_id UUID,
            title VARCHAR(200) NOT NULL,
            body TEXT NOT NULL,
            data JSONB,
            agents_woken INTEGER NOT NULL DEFAULT 0,
            dispatched_to TEXT[],
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_briefing_history_kind_time
            ON briefing_history (kind, created_at);
        """,
    ),
    (
        "order_attempts",
        """
        CREATE TABLE IF NOT EXISTS order_attempts (
            id BIGSERIAL PRIMARY KEY,
            agent_id VARCHAR(64),
            intent_id VARCHAR(64),
            symbol VARCHAR(16),
            side VARCHAR(8),
            rung INTEGER NOT NULL,
            limit_price DOUBLE PRECISION,
            status VARCHAR(32) NOT NULL,
            reason VARCHAR(64),
            fill_price DOUBLE PRECISION,
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_order_attempts_attempted_at
            ON order_attempts (attempted_at);
        """,
    ),
    (
        "trade_outcomes_feedback",
        """
        CREATE TABLE IF NOT EXISTS trade_outcomes_feedback (
            id BIGSERIAL PRIMARY KEY,
            agent_id VARCHAR(64) NOT NULL,
            trade_id VARCHAR(64),
            symbol VARCHAR(16),
            predicted_sl_mult DOUBLE PRECISION,
            actual_mae_atr DOUBLE PRECISION,
            predicted_tp_mult DOUBLE PRECISION,
            actual_mfe_atr DOUBLE PRECISION,
            predicted_slip_bps DOUBLE PRECISION,
            actual_slip_bps DOUBLE PRECISION,
            closed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_trade_feedback_closed_at
            ON trade_outcomes_feedback (closed_at);
        """,
    ),
    (
        "channel_messages",
        """
        CREATE TABLE IF NOT EXISTS channel_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            connector_id UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
            channel VARCHAR(200) NOT NULL,
            author VARCHAR(200) NOT NULL,
            content TEXT NOT NULL,
            message_type VARCHAR(30) NOT NULL DEFAULT 'unknown',
            tickers_mentioned JSONB NOT NULL DEFAULT '[]',
            raw_data JSONB NOT NULL DEFAULT '{}',
            platform_message_id VARCHAR(100) NOT NULL,
            posted_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_channel_messages_connector_id
            ON channel_messages (connector_id);
        CREATE INDEX IF NOT EXISTS ix_channel_messages_message_type
            ON channel_messages (message_type);
        CREATE INDEX IF NOT EXISTS ix_channel_messages_posted_at
            ON channel_messages (posted_at);
        """,
    ),
]


async def _ensure_columns(conn) -> None:
    """Run ALTER TABLE IF NOT EXISTS for every column we need."""
    for table, col, defn in COLUMN_ENSURE:
        sql = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col}" {defn};'
        try:
            await conn.execute(text(sql))
            print(f"  [schema] ensured {table}.{col}")
        except Exception as exc:
            print(f"  [schema] WARN {table}.{col}: {exc}")


async def _ensure_tables(conn) -> None:
    """Run CREATE TABLE IF NOT EXISTS for Phase P/T support tables."""
    for name, ddl in TABLE_ENSURE:
        try:
            await conn.execute(text(ddl))
            print(f"  [schema] ensured table {name}")
        except Exception as exc:
            print(f"  [schema] WARN table {name}: {exc}")


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        # 1) Create any brand-new tables defined in SQLAlchemy models
        await conn.run_sync(Base.metadata.create_all)

        # 2) Self-heal: ensure Phase H/P columns exist even if Alembic failed
        await _ensure_columns(conn)

        # 3) Self-heal: ensure Phase H/P/T support tables exist
        await _ensure_tables(conn)

    await engine.dispose()
    print("  Database tables + columns ensured.")


if __name__ == "__main__":
    asyncio.run(main())
