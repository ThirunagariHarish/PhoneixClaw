"""Merge the two divergent Alembic heads and guarantee agents.engine_type exists.

Prod migrated along `09b0dd176f5d_sync_agent_model_schema` which branched from
`032` and never picked up `033`-`049`, so `agents.engine_type` (added in
`045_pipeline_engine`) is missing on the prod DB. POST /agents raises
`UndefinedColumnError` on INSERT.

This migration:
  1. Collapses the two heads (049_drop_channel_column, 09b0dd176f5d) into one
     so `alembic upgrade head` stops failing with "multiple heads".
  2. Idempotently adds `agents.engine_type` and creates `pipeline_worker_state`
     if the divergent prod branch never applied `045_pipeline_engine`.

Revision ID: 050_merge_heads_engine_type
Revises: 049_drop_channel_column, 09b0dd176f5d
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "050_merge_heads_engine_type"
down_revision: Union[str, Sequence[str], None] = ("049_drop_channel_column", "09b0dd176f5d")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    )
    return result.scalar() is not None


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables WHERE table_name=:t"
        ),
        {"t": table},
    )
    return result.scalar() is not None


def upgrade() -> None:
    if not _has_column("agents", "engine_type"):
        op.add_column(
            "agents",
            sa.Column(
                "engine_type",
                sa.String(20),
                nullable=False,
                server_default="sdk",
            ),
        )

    if not _has_table("pipeline_worker_state"):
        op.create_table(
            "pipeline_worker_state",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("stream_key", sa.String(200), nullable=False),
            sa.Column("last_cursor", sa.String(50), nullable=False, server_default="0-0"),
            sa.Column("signals_processed", sa.Integer, nullable=False, server_default="0"),
            sa.Column("trades_executed", sa.Integer, nullable=False, server_default="0"),
            sa.Column("signals_skipped", sa.Integer, nullable=False, server_default="0"),
            sa.Column("portfolio_snapshot", JSONB, nullable=False, server_default="{}"),
            sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("NOW()"),
            ),
        )
        op.create_index(
            "ix_pws_agent_id", "pipeline_worker_state", ["agent_id"]
        )


def downgrade() -> None:
    # Merge migrations typically do not support downgrade cleanly.
    pass
