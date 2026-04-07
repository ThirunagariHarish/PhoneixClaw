"""Agents tab fix — add agents.error_message and agent_sessions.trading_mode.

Revision ID: 032
Revises: 031
Create Date: 2026-04-08

Stories covered: 1.2, 1.3, 2.5

- agents.error_message (TEXT, nullable): denormalised latest backtest/Claude SDK
  error stored directly on the agent row for fast list-view reads without
  joining agent_backtests.
- agent_sessions.trading_mode (VARCHAR(20), NOT NULL, server_default='live'):
  records whether the Claude Code session was launched in paper or live mode so
  the Agents Tab can surface this per-session without re-parsing config JSONB.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, col: str) -> bool:
    conn = op.get_bind()
    return bool(
        conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ),
            {"t": table, "c": col},
        ).first()
    )


def upgrade() -> None:
    if not _has_column("agents", "error_message"):
        op.add_column(
            "agents",
            sa.Column("error_message", sa.Text, nullable=True),
        )
    if not _has_column("agent_sessions", "trading_mode"):
        op.add_column(
            "agent_sessions",
            sa.Column(
                "trading_mode",
                sa.String(20),
                nullable=False,
                server_default="live",
            ),
        )


def downgrade() -> None:
    if _has_column("agent_sessions", "trading_mode"):
        op.drop_column("agent_sessions", "trading_mode")
    if _has_column("agents", "error_message"):
        op.drop_column("agents", "error_message")
