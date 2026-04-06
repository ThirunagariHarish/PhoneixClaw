"""Phase 1: Add decision tracking to agent_trades, model_selection to backtests.

Adds decision_status and rejection_reason columns to agent_trades for
tracking processed/accepted/rejected trade decisions. Adds model_selection
JSONB to agent_backtests for intelligent model selection results.

Revision ID: 008
Revises: 007
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agent trades: decision tracking
    op.add_column(
        "agent_trades",
        sa.Column("decision_status", sa.String(20), nullable=False, server_default="accepted"),
    )
    op.add_column(
        "agent_trades",
        sa.Column("rejection_reason", sa.Text, nullable=True),
    )
    op.create_index("idx_agent_trades_decision_status", "agent_trades", ["decision_status"])

    # Agent backtests: model selection results
    op.add_column(
        "agent_backtests",
        sa.Column("model_selection", sa.JSON, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("agent_backtests", "model_selection")
    op.drop_index("idx_agent_trades_decision_status", table_name="agent_trades")
    op.drop_column("agent_trades", "rejection_reason")
    op.drop_column("agent_trades", "decision_status")
