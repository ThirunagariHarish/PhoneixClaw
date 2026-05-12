"""Add feature store tables for backtest pipeline.

Creates three tables to support feature-store architecture:
- enriched_trades: cached enriched features per parsed trade
- daily_bars: historical OHLCV data from external providers
- agent_backtest_step_logs: granular progress tracking for backtest steps

Revision ID: 051_feature_store
Revises: 050_merge_heads_engine_type
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "051_feature_store"
down_revision: Union[str, None] = "050_merge_heads_engine_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. enriched_trades: cached enriched features per parsed trade
    op.create_table(
        "enriched_trades",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("parsed_trade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("computed_version", sa.String(32), nullable=False, server_default="v1"),
    )
    op.create_index(
        "ix_enriched_trades_parsed_trade_id",
        "enriched_trades",
        ["parsed_trade_id"],
    )
    op.create_index(
        "ix_enriched_trades_ticker_entry",
        "enriched_trades",
        ["ticker", "entry_time"],
    )
    # Unique constraint on (parsed_trade_id, computed_version)
    op.create_index(
        "uq_enriched_trades_parsed_version",
        "enriched_trades",
        ["parsed_trade_id", "computed_version"],
        unique=True,
    )

    # 2. daily_bars: historical OHLCV data
    op.create_table(
        "daily_bars",
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("open", sa.Numeric(20, 6), nullable=True),
        sa.Column("high", sa.Numeric(20, 6), nullable=True),
        sa.Column("low", sa.Numeric(20, 6), nullable=True),
        sa.Column("close", sa.Numeric(20, 6), nullable=True),
        sa.Column("adj_close", sa.Numeric(20, 6), nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="tiingo"),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("ticker", "date"),
    )

    # 3. agent_backtest_step_logs: granular progress tracking
    op.create_table(
        "agent_backtest_step_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "backtest_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("step", sa.String(100), nullable=False),
        sa.Column("sub_progress_pct", sa.Integer, nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_foreign_key(
        "fk_agent_backtest_step_logs_backtest_id",
        "agent_backtest_step_logs",
        "agent_backtests",
        ["backtest_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_agent_backtest_step_logs_backtest_ts",
        "agent_backtest_step_logs",
        ["backtest_id", "ts"],
    )


def downgrade() -> None:
    # Drop in reverse order to respect foreign keys
    op.drop_index("ix_agent_backtest_step_logs_backtest_ts")
    op.drop_constraint(
        "fk_agent_backtest_step_logs_backtest_id",
        "agent_backtest_step_logs",
        type_="foreignkey",
    )
    op.drop_table("agent_backtest_step_logs")

    op.drop_table("daily_bars")

    op.drop_index("uq_enriched_trades_parsed_version", table_name="enriched_trades")
    op.drop_index("ix_enriched_trades_ticker_entry", table_name="enriched_trades")
    op.drop_index("ix_enriched_trades_parsed_trade_id", table_name="enriched_trades")
    op.drop_table("enriched_trades")
