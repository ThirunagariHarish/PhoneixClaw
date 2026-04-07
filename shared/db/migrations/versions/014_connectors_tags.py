"""Add tags column to connectors table.

The Connector model declares `tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)`
but the original `003_remaining_tables.py` migration that created the connectors table
never added this column. Local dev works (init_db.py uses Base.metadata.create_all which
reads the model) but production databases created via alembic are missing it, causing
IntegrityError on POST /api/v2/connectors.

This migration is idempotent — it checks for the column before adding it.

Revision ID: 014
Revises: 013
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(sa.text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'connectors' AND column_name = 'tags'
    """)).first()
    if not exists:
        op.add_column(
            "connectors",
            sa.Column("tags", JSONB(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    op.drop_column("connectors", "tags")
