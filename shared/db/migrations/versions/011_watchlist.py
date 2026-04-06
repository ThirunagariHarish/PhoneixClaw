"""Phase 1.5: Watchlist table for paper trading.

In PAPER mode, agents add tickers to a Robinhood watchlist instead of
executing real trades. This table tracks the entry context for simulated P&L.

Revision ID: 011
Revises: 010
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False, server_default="buy"),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("entry_price_at_add", sa.Float, nullable=False),
        sa.Column("current_price", sa.Float, nullable=True),
        sa.Column("simulated_pnl", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("simulated_pnl_pct", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("signal_data", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_price_update", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_watchlist_agent", "watchlist", ["agent_id"])
    op.create_index("idx_watchlist_ticker", "watchlist", ["ticker"])
    op.create_index("idx_watchlist_status", "watchlist", ["status"])


def downgrade() -> None:
    op.drop_index("idx_watchlist_status", table_name="watchlist")
    op.drop_index("idx_watchlist_ticker", table_name="watchlist")
    op.drop_index("idx_watchlist_agent", table_name="watchlist")
    op.drop_table("watchlist")
