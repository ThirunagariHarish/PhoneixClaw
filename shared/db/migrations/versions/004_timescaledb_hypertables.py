"""TimescaleDB hypertables and retention policies.

Revision ID: 004
Revises: 003
Create Date: 2026-03-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_timescaledb(connection) -> bool:
    """Check if TimescaleDB extension is available on this server."""
    result = connection.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()
    use_timescale = _has_timescaledb(conn)

    if use_timescale:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    op.create_table(
        "market_bars",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("vwap", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
    )
    if use_timescale:
        op.execute("SELECT create_hypertable('market_bars', 'time', chunk_time_interval => INTERVAL '7 days')")
    op.create_index("ix_market_bars_symbol_time", "market_bars", ["symbol", "time"])

    op.create_table(
        "performance_metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", sa.String(100), nullable=True),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    if use_timescale:
        op.execute("SELECT create_hypertable('performance_metrics', 'time', chunk_time_interval => INTERVAL '7 days')")
    op.create_index("ix_perf_metrics_agent_time", "performance_metrics", ["agent_id", "time"])

    op.create_table(
        "agent_heartbeats",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cpu_pct", sa.Float(), nullable=True),
        sa.Column("memory_mb", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("positions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    if use_timescale:
        op.execute("SELECT create_hypertable('agent_heartbeats', 'time', chunk_time_interval => INTERVAL '1 day')")
    op.create_index("ix_heartbeats_instance_time", "agent_heartbeats", ["instance_id", "time"])

    if use_timescale:
        op.execute("SELECT add_retention_policy('market_bars', INTERVAL '2 years')")
        op.execute("SELECT add_retention_policy('performance_metrics', INTERVAL '1 year')")
        op.execute("SELECT add_retention_policy('agent_heartbeats', INTERVAL '90 days')")


def downgrade() -> None:
    conn = op.get_bind()
    use_timescale = _has_timescaledb(conn)
    if use_timescale:
        op.execute("SELECT remove_retention_policy('agent_heartbeats', if_exists => true)")
        op.execute("SELECT remove_retention_policy('performance_metrics', if_exists => true)")
        op.execute("SELECT remove_retention_policy('market_bars', if_exists => true)")
    op.drop_table("agent_heartbeats")
    op.drop_table("performance_metrics")
    op.drop_table("market_bars")
