"""Drop legacy channel column after channel_id_snowflake verification.

IMPORTANT: This migration is a SKELETON ONLY. Do NOT apply until:
1. Migration 048 has been running in production for 7 days
2. All channel_id_snowflake values are populated and verified
3. All code and agents have been updated to use channel_id_snowflake
4. Manual verification confirms no NULL snowflake values in active data

Apply this migration 1 week after 048, after full verification.

Revision ID: 049_drop_channel_column
Revises: 048_channel_id_snowflake
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_drop_channel_column"
down_revision: Union[str, None] = "048_channel_id_snowflake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    MANUAL VERIFICATION REQUIRED BEFORE APPLYING:

    Run these checks first:
    1. SELECT COUNT(*) FROM channel_messages WHERE channel_id_snowflake IS NULL;
       Expected: 0

    2. SELECT COUNT(*) FROM channel_messages WHERE channel_id_snowflake !~ '^[0-9]{15,20}$';
       Expected: 0

    3. Verify all agents and services use channel_id_snowflake

    4. Test backtest pipeline in staging with --source postgres

    If any check fails, DO NOT APPLY this migration.
    """

    # Set default for NULL values (should be none if verification passed)
    op.execute("UPDATE channel_messages SET channel_id_snowflake = 'UNKNOWN' WHERE channel_id_snowflake IS NULL")

    # Make channel_id_snowflake NOT NULL
    op.alter_column("channel_messages", "channel_id_snowflake", nullable=False)

    # Drop legacy channel column
    op.drop_column("channel_messages", "channel")


def downgrade() -> None:
    # Re-add legacy channel column
    op.add_column(
        "channel_messages",
        sa.Column("channel", sa.String(200), nullable=True)
    )

    # Backfill from snowflake
    op.execute("UPDATE channel_messages SET channel = channel_id_snowflake")

    # Make it nullable again as it was before
    op.alter_column("channel_messages", "channel_id_snowflake", nullable=True)
