"""Phase 4: Supervisor agent pending_improvements column.

Adds pending_improvements (JSONB) and last_research_at to agents for the
AutoResearch supervisor agent's staged change workflow.

Revision ID: 013
Revises: 012
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("pending_improvements", sa.dialects.postgresql.JSONB,
                  nullable=False, server_default="{}"),
    )
    op.add_column(
        "agents",
        sa.Column("last_research_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "last_research_at")
    op.drop_column("agents", "pending_improvements")
