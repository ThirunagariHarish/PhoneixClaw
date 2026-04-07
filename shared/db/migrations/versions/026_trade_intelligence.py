"""Phase T (T8 + T11): trade-intelligence support tables.

Adds:
- order_attempts           — every rung of the T8 adaptive retry ladder
- trade_outcomes_feedback  — per-trade (predicted vs actual) for T11 bias correction

Revision ID: 026
Revises: 016
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name=:n"),
        {"n": name},
    ).first())


def upgrade() -> None:
    if not _has_table("order_attempts"):
        op.create_table(
            "order_attempts",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("agent_id", sa.String(64), nullable=True, index=True),
            sa.Column("intent_id", sa.String(64), nullable=True, index=True),
            sa.Column("symbol", sa.String(16), nullable=True),
            sa.Column("side", sa.String(8), nullable=True),
            sa.Column("rung", sa.Integer, nullable=False),
            sa.Column("limit_price", sa.Float, nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("reason", sa.String(64), nullable=True),
            sa.Column("fill_price", sa.Float, nullable=True),
            sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index("ix_order_attempts_attempted_at", "order_attempts", ["attempted_at"])

    if not _has_table("trade_outcomes_feedback"):
        op.create_table(
            "trade_outcomes_feedback",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("agent_id", sa.String(64), nullable=False, index=True),
            sa.Column("trade_id", sa.String(64), nullable=True, index=True),
            sa.Column("symbol", sa.String(16), nullable=True),
            sa.Column("predicted_sl_mult", sa.Float, nullable=True),
            sa.Column("actual_mae_atr", sa.Float, nullable=True),
            sa.Column("predicted_tp_mult", sa.Float, nullable=True),
            sa.Column("actual_mfe_atr", sa.Float, nullable=True),
            sa.Column("predicted_slip_bps", sa.Float, nullable=True),
            sa.Column("actual_slip_bps", sa.Float, nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index("ix_trade_feedback_closed_at", "trade_outcomes_feedback", ["closed_at"])


def downgrade() -> None:
    op.drop_table("trade_outcomes_feedback")
    op.drop_table("order_attempts")
