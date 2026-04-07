"""Briefing History table — persistent log of all scheduled briefings.

Revision ID: 028
Revises: 027
Create Date: 2026-04-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name=:n"),
        {"n": name},
    ).first())


def upgrade() -> None:
    if _has_table("briefing_history"):
        return
    op.create_table(
        "briefing_history",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="morning"),
        sa.Column("agent_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("data", sa.JSON, nullable=True),
        sa.Column("agents_woken", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dispatched_to", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_briefing_history_kind_time",
                    "briefing_history", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_table("briefing_history")
