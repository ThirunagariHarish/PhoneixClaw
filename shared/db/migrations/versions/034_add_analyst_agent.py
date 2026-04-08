"""add analyst agent fields

Revision ID: 034_add_analyst_agent
Revises: 09b0dd176f5d
Create Date: 2026-04-10 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "034_add_analyst_agent"
# Merge migration: both 09b0dd176f5d (sync_agent_model_schema) and 033_pm_phase15
# are heads off 032. This migration merges them into a single head.
down_revision: Union[str, Sequence[str], None] = ("09b0dd176f5d", "033_pm_phase15")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import text
    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"),
        {"t": table, "c": column},
    )
    return result.scalar() is not None


def _has_constraint(table: str, constraint: str) -> bool:
    from sqlalchemy import text
    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM information_schema.table_constraints WHERE table_name=:t AND constraint_name=:c"),
        {"t": table, "c": constraint},
    )
    return result.scalar() is not None


def upgrade() -> None:
    # Add new columns to trade_signals (idempotent)
    if not _has_column("trade_signals", "analyst_persona"):
        op.add_column("trade_signals", sa.Column("analyst_persona", sa.String(50), nullable=True))
    if not _has_column("trade_signals", "tool_signals_used"):
        op.add_column("trade_signals", sa.Column("tool_signals_used", JSONB, nullable=True))
    if not _has_column("trade_signals", "risk_reward_ratio"):
        op.add_column("trade_signals", sa.Column("risk_reward_ratio", sa.Float(), nullable=True))
    if not _has_column("trade_signals", "take_profit"):
        op.add_column("trade_signals", sa.Column("take_profit", sa.Float(), nullable=True))
    if not _has_column("trade_signals", "entry_price"):
        op.add_column("trade_signals", sa.Column("entry_price", sa.Float(), nullable=True))
    if not _has_column("trade_signals", "stop_loss"):
        op.add_column("trade_signals", sa.Column("stop_loss", sa.Float(), nullable=True))
    if not _has_column("trade_signals", "pattern_name"):
        op.add_column("trade_signals", sa.Column("pattern_name", sa.String(100), nullable=True))

    # Update agents.type CHECK constraint to include 'analyst'
    from sqlalchemy import text
    conn = op.get_bind()

    try:
        conn.execute(text(
            "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_type_check"
        ))
    except Exception:
        pass
    try:
        conn.execute(text(
            "ALTER TABLE agents ADD CONSTRAINT agents_type_check "
            "CHECK (type IN ('trading', 'trend', 'sentiment', 'analyst', 'system', "
            "'unusual_whales', 'social_sentiment', 'strategy', 'supervisor', "
            "'morning_briefing', 'daily_summary', 'eod_analysis', 'trade_feedback', "
            "'position_monitor'))"
        ))
    except Exception:
        pass  # Constraint may not be enforced or may already be updated


def downgrade() -> None:
    from sqlalchemy import text
    conn = op.get_bind()

    for col in ["analyst_persona", "tool_signals_used", "risk_reward_ratio",
                "take_profit", "entry_price", "stop_loss", "pattern_name"]:
        if _has_column("trade_signals", col):
            op.drop_column("trade_signals", col)

    try:
        conn.execute(text("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_type_check"))
        conn.execute(text(
            "ALTER TABLE agents ADD CONSTRAINT agents_type_check "
            "CHECK (type IN ('trading', 'trend', 'sentiment', 'system', "
            "'unusual_whales', 'social_sentiment', 'strategy', 'supervisor', "
            "'morning_briefing', 'daily_summary', 'eod_analysis', 'trade_feedback', "
            "'position_monitor'))"
        ))
    except Exception:
        pass
