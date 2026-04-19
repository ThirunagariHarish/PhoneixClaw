"""Drop openclaw_instances table (Phase F).

Revision ID: 047_drop_openclaw_instances
Revises: 044_ml_platform_tables
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "047_drop_openclaw_instances"
down_revision: Union[str, None] = "044_ml_platform_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_openclaw_instances_name", table_name="openclaw_instances")
    op.drop_table("openclaw_instances")


def downgrade() -> None:
    op.create_table(
        "openclaw_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="18800"),
        sa.Column("role", sa.String(50), nullable=False, server_default="general"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ONLINE"),
        sa.Column("node_type", sa.String(10), nullable=False, server_default="vps"),
        sa.Column("auto_registered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_offline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_openclaw_instances_name", "openclaw_instances", ["name"], unique=True)
