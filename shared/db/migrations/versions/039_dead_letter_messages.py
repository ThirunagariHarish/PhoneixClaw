"""Add dead_letter_messages table for failed message ingestion.

Revision ID: 039_dead_letter_messages
Revises: 038_decision_trail
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "039_dead_letter_messages"
down_revision = "038_decision_trail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dead_letter_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("connector_id", sa.String(100), nullable=False, index=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("dead_letter_messages")
