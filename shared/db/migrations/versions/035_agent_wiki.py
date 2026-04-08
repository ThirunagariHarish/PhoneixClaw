"""add agent wiki tables

Revision ID: 035_agent_wiki
Revises: 034_add_analyst_agent
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "035_agent_wiki"
down_revision: Union[str, Sequence[str], None] = "034_add_analyst_agent"
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
    if not _has_table("agent_wiki_entries"):
        op.create_table(
            "agent_wiki_entries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("category", sa.String(50), nullable=False),
            sa.Column("subcategory", sa.String(100), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column(
                "tags",
                ARRAY(sa.String),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "symbols",
                ARRAY(sa.String),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("confidence_score", sa.Float, nullable=False, server_default="0.5"),
            sa.Column(
                "trade_ref_ids",
                ARRAY(UUID(as_uuid=True)),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("created_by", sa.String(10), nullable=False, server_default="agent"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("is_shared", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _has_table("agent_wiki_entry_versions"):
        op.create_table(
            "agent_wiki_entry_versions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "entry_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agent_wiki_entries.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("updated_by", sa.String(10), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("change_reason", sa.String(500), nullable=True),
        )

    # Indexes on agent_wiki_entries
    if not _has_index("ix_agent_wiki_entries_agent_id"):
        op.create_index("ix_agent_wiki_entries_agent_id", "agent_wiki_entries", ["agent_id"])
    if not _has_index("ix_agent_wiki_entries_category"):
        op.create_index("ix_agent_wiki_entries_category", "agent_wiki_entries", ["category"])
    if not _has_index("ix_agent_wiki_entries_is_shared"):
        op.create_index("ix_agent_wiki_entries_is_shared", "agent_wiki_entries", ["is_shared"])
    if not _has_index("ix_agent_wiki_entries_confidence_score"):
        op.create_index(
            "ix_agent_wiki_entries_confidence_score", "agent_wiki_entries", ["confidence_score"]
        )

    # Index on agent_wiki_entry_versions
    if not _has_index("ix_agent_wiki_entry_versions_entry_id"):
        op.create_index(
            "ix_agent_wiki_entry_versions_entry_id", "agent_wiki_entry_versions", ["entry_id"]
        )


def downgrade() -> None:
    if _has_table("agent_wiki_entry_versions"):
        op.drop_table("agent_wiki_entry_versions")
    if _has_table("agent_wiki_entries"):
        op.drop_table("agent_wiki_entries")
