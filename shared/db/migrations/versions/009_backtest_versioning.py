"""Phase 1.1: Add backtesting_version column for versioned re-runs.

Each backtest re-run for the same agent gets a new version number, and
results are written to data/backtest_{agent_id}/output/v{N}/ instead of
overwriting the previous run.

Revision ID: 009
Revises: 008
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_backtests",
        sa.Column("backtesting_version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index(
        "idx_agent_backtests_agent_version",
        "agent_backtests",
        ["agent_id", "backtesting_version"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_backtests_agent_version", table_name="agent_backtests")
    op.drop_column("agent_backtests", "backtesting_version")
