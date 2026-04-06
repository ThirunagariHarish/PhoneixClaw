"""Phase 3.1: Notification dispatcher columns + preferences table.

Adds event_type, channels_sent, data columns to notifications and creates
a notification_preferences table for per-user channel toggles.

Revision ID: 012
Revises: 011
Create Date: 2026-04-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("event_type", sa.String(50), nullable=False, server_default="info"),
    )
    op.add_column(
        "notifications",
        sa.Column("channels_sent", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "notifications",
        sa.Column("data", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_notifications_event_type", "notifications", ["event_type"])

    op.alter_column("notifications", "user_id", nullable=True)

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "channel", name="uq_notif_pref_user_channel"),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.alter_column("notifications", "user_id", nullable=False)
    op.drop_index("idx_notifications_event_type", table_name="notifications")
    op.drop_column("notifications", "data")
    op.drop_column("notifications", "channels_sent")
    op.drop_column("notifications", "event_type")
