"""Add engine_type to agents and pipeline_worker_state table.

Supports the Pipeline Engine: a pure-Python, zero-AI alternative to the
Claude SDK engine.  Existing agents default to engine_type='sdk'.

Revision ID: 045_pipeline_engine
Revises: 044_ml_platform_tables
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "045_pipeline_engine"
down_revision = "044_ml_platform_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("engine_type", sa.String(20), nullable=False, server_default="sdk"),
    )

    op.create_table(
        "pipeline_worker_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("stream_key", sa.String(200), nullable=False),
        sa.Column("last_cursor", sa.String(50), nullable=False, server_default="0-0"),
        sa.Column("signals_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("trades_executed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("signals_skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("portfolio_snapshot", JSONB, nullable=False, server_default="{}"),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_pws_agent_id", "pipeline_worker_state", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_pws_agent_id", table_name="pipeline_worker_state")
    op.drop_table("pipeline_worker_state")
    op.drop_column("agents", "engine_type")
