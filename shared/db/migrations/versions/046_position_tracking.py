"""Add current_quantity and position_status to agent_trades for position tracking.

Supports percentage-sell calculations and position lifecycle management in
pipeline engine. Backfills from exit_time: closed positions have 0 current_quantity,
open positions have current_quantity = quantity.

Revision ID: 046_position_tracking
Revises: 045_pipeline_engine
"""
import sqlalchemy as sa
from alembic import op

revision = "046_position_tracking"
down_revision = "045_pipeline_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns with nullable=True initially
    op.add_column(
        "agent_trades",
        sa.Column("current_quantity", sa.Integer, nullable=True),
    )
    op.add_column(
        "agent_trades",
        sa.Column("position_status", sa.String(20), nullable=True),
    )

    # Backfill: closed positions have 0 current_quantity, open have quantity
    op.execute(
        """
        UPDATE agent_trades
        SET current_quantity = CASE WHEN exit_time IS NOT NULL THEN 0 ELSE quantity END,
            position_status = CASE WHEN exit_time IS NOT NULL THEN 'closed' ELSE 'open' END
        """
    )

    # Make columns NOT NULL with defaults
    op.alter_column(
        "agent_trades",
        "current_quantity",
        nullable=False,
        server_default="0",
    )
    op.alter_column(
        "agent_trades",
        "position_status",
        nullable=False,
        server_default="open",
    )

    # Partial index for fast position lookups
    op.execute(
        """
        CREATE INDEX ix_agent_trades_position_lookup
        ON agent_trades(agent_id, ticker, strike, expiry, position_status)
        WHERE position_status IN ('open', 'partially_closed')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_trades_position_lookup")
    op.drop_column("agent_trades", "position_status")
    op.drop_column("agent_trades", "current_quantity")
