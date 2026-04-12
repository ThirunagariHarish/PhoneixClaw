"""Add channel_messages table for ingested Discord/Reddit/Twitter messages.

The channel_messages table stores every message ingested by the message_ingestion
service. It is the source of truth for the dashboard Feed tab and is queried by
the backfill and polling endpoints. Without this table the entire feed pipeline
fails with UndefinedTableError.

Revision ID: 043_channel_messages
Revises: 042_watchlist_items
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "043_channel_messages"
down_revision = "042_watchlist_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "connector_id",
            UUID(as_uuid=True),
            sa.ForeignKey("connectors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(200), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("message_type", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("tickers_mentioned", JSONB, nullable=False, server_default="[]"),
        sa.Column("raw_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("platform_message_id", sa.String(100), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_channel_messages_connector_id", "channel_messages", ["connector_id"])
    op.create_index("ix_channel_messages_message_type", "channel_messages", ["message_type"])
    op.create_index("ix_channel_messages_posted_at", "channel_messages", ["posted_at"])


def downgrade() -> None:
    op.drop_index("ix_channel_messages_posted_at", table_name="channel_messages")
    op.drop_index("ix_channel_messages_message_type", table_name="channel_messages")
    op.drop_index("ix_channel_messages_connector_id", table_name="channel_messages")
    op.drop_table("channel_messages")
