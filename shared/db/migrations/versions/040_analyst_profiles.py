"""Add analyst_profiles table for behavior modeling.

Revision ID: 040_analyst_profiles
Revises: 039_dead_letter_messages
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "040_analyst_profiles"
down_revision = "039_dead_letter_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analyst_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("analyst_name", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("channel", sa.String(100), nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("win_rate_10", sa.Float, nullable=True),
        sa.Column("win_rate_20", sa.Float, nullable=True),
        sa.Column("avg_hold_hours", sa.Float, nullable=True),
        sa.Column("median_exit_pnl", sa.Float, nullable=True),
        sa.Column("exit_pnl_p25", sa.Float, nullable=True),
        sa.Column("exit_pnl_p75", sa.Float, nullable=True),
        sa.Column("avg_entry_hour", sa.Float, nullable=True),
        sa.Column("avg_exit_hour", sa.Float, nullable=True),
        sa.Column("preferred_exit_dow", JSONB, nullable=True),
        sa.Column("drawdown_tolerance", sa.Float, nullable=True),
        sa.Column("conviction_score", sa.Float, nullable=True),
        sa.Column("post_earnings_sell_rate", sa.Float, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("profile_data", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("analyst_profiles")
