"""add consolidation_runs table

Revision ID: 036_consolidation_runs
Revises: 035_agent_wiki
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "036_consolidation_runs"
down_revision: Union[str, Sequence[str], None] = "035_agent_wiki"
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
    if not _has_table("consolidation_runs"):
        op.create_table(
            "consolidation_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("run_type", sa.String(20), nullable=False, server_default="nightly"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trades_analyzed", sa.Integer, nullable=False, server_default="0"),
            sa.Column("wiki_entries_written", sa.Integer, nullable=False, server_default="0"),
            sa.Column("wiki_entries_updated", sa.Integer, nullable=False, server_default="0"),
            sa.Column("wiki_entries_pruned", sa.Integer, nullable=False, server_default="0"),
            sa.Column("patterns_found", sa.Integer, nullable=False, server_default="0"),
            sa.Column("rules_proposed", sa.Integer, nullable=False, server_default="0"),
            sa.Column("consolidation_report", sa.Text, nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _has_index("ix_consolidation_runs_agent_id"):
        op.create_index("ix_consolidation_runs_agent_id", "consolidation_runs", ["agent_id"])
    if not _has_index("ix_consolidation_runs_status"):
        op.create_index("ix_consolidation_runs_status", "consolidation_runs", ["status"])


def downgrade() -> None:
    if _has_table("consolidation_runs"):
        op.drop_table("consolidation_runs")
