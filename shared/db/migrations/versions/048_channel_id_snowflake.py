"""Add channel_id_snowflake column and backfill_run_id for DB-backed backtesting.

Phase C.6 migration: Adds canonical snowflake identifiers for Discord channels,
enabling DB-only backtest pipeline without live Discord API calls.

Revision ID: 048_channel_id_snowflake
Revises: 046_position_tracking, 047_drop_openclaw_instances
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "048_channel_id_snowflake"
down_revision: Union[str, Sequence[str], None] = ("046_position_tracking", "047_drop_openclaw_instances")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add channel_id_snowflake column to channel_messages
    op.add_column(
        "channel_messages",
        sa.Column("channel_id_snowflake", sa.String(20), nullable=True)
    )

    # Backfill snowflake from existing channel column (where it's numeric)
    op.execute(
        "UPDATE channel_messages SET channel_id_snowflake = channel WHERE channel ~ '^[0-9]+$'"
    )

    # Add backfill_run_id for traceability
    op.add_column(
        "channel_messages",
        sa.Column("backfill_run_id", UUID(as_uuid=True), nullable=True)
    )

    # Create composite index for efficient backtest queries
    op.create_index(
        "ix_channel_messages_channel_posted",
        "channel_messages",
        ["channel_id_snowflake", "posted_at"]
    )

    # Add unique constraint on platform_message_id for idempotent backfill
    op.create_unique_constraint(
        "uq_channel_messages_platform_id",
        "channel_messages",
        ["platform_message_id"]
    )

    # Add channel_id to backtest_trades for direct joins
    op.add_column(
        "backtest_trades",
        sa.Column("channel_id", sa.String(20), nullable=True)
    )

    # Backfill channel_id from channel_messages FK
    op.execute("""
        UPDATE backtest_trades bt
        SET channel_id = (
            SELECT cm.channel_id_snowflake
            FROM channel_messages cm
            WHERE cm.id = bt.signal_message_id
        )
        WHERE bt.signal_message_id IS NOT NULL
    """)

    # Index for backtest queries by channel
    op.create_index(
        "ix_backtest_trades_channel_id",
        "backtest_trades",
        ["channel_id"]
    )


def downgrade() -> None:
    # Drop indexes first
    op.drop_index("ix_backtest_trades_channel_id", table_name="backtest_trades")
    op.drop_column("backtest_trades", "channel_id")

    op.drop_constraint("uq_channel_messages_platform_id", "channel_messages", type_="unique")
    op.drop_index("ix_channel_messages_channel_posted", table_name="channel_messages")

    op.drop_column("channel_messages", "backfill_run_id")
    op.drop_column("channel_messages", "channel_id_snowflake")
