"""Trade signal logging for RL feedback loop.

Every decision the agent makes (execute/reject/watchlist/paper) is logged
with its feature snapshot. At EOD, enriched with outcome prices and
was_missed_opportunity flag for rejected signals that would have been profitable.

Revision ID: 015
Revises: 014
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_signals",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(10), nullable=True),
        sa.Column("signal_source", sa.String(30), nullable=False, server_default="discord"),
        sa.Column("source_message_id", sa.String(100), nullable=True),
        sa.Column("predicted_prob", sa.Float, nullable=True),
        sa.Column("model_confidence", sa.Float, nullable=True),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("features", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("outcome_price_1h", sa.Float, nullable=True),
        sa.Column("outcome_price_4h", sa.Float, nullable=True),
        sa.Column("outcome_price_eod", sa.Float, nullable=True),
        sa.Column("realized_pnl_pct", sa.Float, nullable=True),
        sa.Column("was_missed_opportunity", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_trade_signals_agent", "trade_signals", ["agent_id"])
    op.create_index("idx_trade_signals_ticker", "trade_signals", ["ticker"])
    op.create_index("idx_trade_signals_decision", "trade_signals", ["decision"])
    op.create_index("idx_trade_signals_created", "trade_signals", ["created_at"])
    op.create_index("idx_trade_signals_missed", "trade_signals", ["was_missed_opportunity"])


def downgrade() -> None:
    op.drop_index("idx_trade_signals_missed", table_name="trade_signals")
    op.drop_index("idx_trade_signals_created", table_name="trade_signals")
    op.drop_index("idx_trade_signals_decision", table_name="trade_signals")
    op.drop_index("idx_trade_signals_ticker", table_name="trade_signals")
    op.drop_index("idx_trade_signals_agent", table_name="trade_signals")
    op.drop_table("trade_signals")
