"""Polymarket — add pm_strategies.last_successful_backtest_at (BUG-1).

Revision ID: 031
Revises: 030
Create Date: 2026-04-07

PRD §5 rule 1 requires that a strategy cannot be promoted PAPER -> LIVE unless
a walk-forward backtest (F10) is attached and was completed within the last
30 days. Phase 11's promotion gate did not enforce this. This migration adds
a nullable timestamp column that the backtest pipeline updates on successful
completion; the promotion gate reads it and rejects promotion when it is
None or older than `max_backtest_age_days`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, col: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    ).first())


def upgrade() -> None:
    if not _has_column("pm_strategies", "last_successful_backtest_at"):
        op.add_column(
            "pm_strategies",
            sa.Column(
                "last_successful_backtest_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _has_column("pm_strategies", "last_successful_backtest_at"):
        op.drop_column("pm_strategies", "last_successful_backtest_at")
