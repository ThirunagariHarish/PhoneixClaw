"""Phase 1.3: Position sub-agent fields on agent_sessions.

Adds parent_agent_id, position_ticker, position_side, session_role, and
runtime visibility fields (host_name, pid) to support position monitor
sub-agents that run as separate Claude Code sessions per open position.

Revision ID: 010
Revises: 009
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column("parent_agent_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("position_ticker", sa.String(20), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("position_side", sa.String(10), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("session_role", sa.String(30), nullable=False, server_default="primary"),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("host_name", sa.String(100), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("pid", sa.Integer, nullable=True),
    )

    op.create_foreign_key(
        "fk_agent_sessions_parent",
        "agent_sessions", "agent_sessions",
        ["parent_agent_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_agent_sessions_parent", "agent_sessions", ["parent_agent_id"])
    op.create_index("idx_agent_sessions_role", "agent_sessions", ["session_role"])


def downgrade() -> None:
    op.drop_index("idx_agent_sessions_role", table_name="agent_sessions")
    op.drop_index("idx_agent_sessions_parent", table_name="agent_sessions")
    op.drop_constraint("fk_agent_sessions_parent", "agent_sessions", type_="foreignkey")
    op.drop_column("agent_sessions", "pid")
    op.drop_column("agent_sessions", "host_name")
    op.drop_column("agent_sessions", "session_role")
    op.drop_column("agent_sessions", "position_side")
    op.drop_column("agent_sessions", "position_ticker")
    op.drop_column("agent_sessions", "parent_agent_id")
