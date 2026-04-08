"""add context_sessions table

Revision ID: 037_context_sessions
Revises: 036_consolidation_runs
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "037_context_sessions"
down_revision: Union[str, Sequence[str], None] = "036_consolidation_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    from sqlalchemy import text

    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name=:t"),
        {"t": table},
    )
    return result.scalar() is not None


def _has_index(index: str) -> bool:
    from sqlalchemy import text

    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname=:i"),
        {"i": index},
    )
    return result.scalar() is not None


def upgrade() -> None:
    if not _has_table("context_sessions"):
        op.create_table(
            "context_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("session_id", UUID(as_uuid=True), nullable=True),
            sa.Column("session_type", sa.String(20), nullable=False, server_default="chat"),
            sa.Column("signal_symbol", sa.String(20), nullable=True),
            sa.Column("token_budget", sa.Integer, nullable=False, server_default="8000"),
            sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
            sa.Column("wiki_entries_injected", sa.Integer, nullable=False, server_default="0"),
            sa.Column("trades_injected", sa.Integer, nullable=False, server_default="0"),
            sa.Column(
                "manifest_sections_injected",
                sa.ARRAY(sa.String),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("quality_score", sa.Float, nullable=True),
            sa.Column(
                "built_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _has_index("ix_context_sessions_agent_id"):
        op.create_index("ix_context_sessions_agent_id", "context_sessions", ["agent_id"])
    if not _has_index("ix_context_sessions_built_at"):
        op.create_index("ix_context_sessions_built_at", "context_sessions", ["built_at"])


def downgrade() -> None:
    if _has_table("context_sessions"):
        op.drop_table("context_sessions")
