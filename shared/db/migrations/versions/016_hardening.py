"""Phase H4 + H7: hardening — retention indexes + agent budget columns.

Adds:
- created_at indexes on log/notification/message tables (for fast retention DELETE)
- daily/monthly token budget columns on agents table

Revision ID: 016
Revises: 015
Create Date: 2026-04-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_if_missing(name: str, table: str, columns: list[str]):
    """Idempotent index creation — alembic doesn't have it natively for indexes."""
    conn = op.get_bind()
    exists = conn.execute(sa.text("""
        SELECT 1 FROM pg_indexes WHERE indexname = :name
    """), {"name": name}).first()
    if not exists:
        op.create_index(name, table, columns)


def _add_column_if_missing(table: str, column_name: str, column_def):
    """Idempotent column add."""
    conn = op.get_bind()
    exists = conn.execute(sa.text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = :table AND column_name = :col
    """), {"table": table, "col": column_name}).first()
    if not exists:
        op.add_column(table, column_def)


def upgrade() -> None:
    # Retention indexes (idempotent — only create if missing)
    _create_index_if_missing("idx_system_logs_created_at", "system_logs", ["created_at"])
    _create_index_if_missing("idx_agent_logs_created_at", "agent_logs", ["created_at"])
    _create_index_if_missing("idx_agent_messages_created_at", "agent_messages", ["created_at"])
    _create_index_if_missing("idx_notifications_created_at", "notifications", ["created_at"])
    _create_index_if_missing("idx_notifications_read_created", "notifications", ["read", "created_at"])

    # Budget columns on agents
    _add_column_if_missing(
        "agents", "daily_token_budget_usd",
        sa.Column("daily_token_budget_usd", sa.Float, nullable=True),
    )
    _add_column_if_missing(
        "agents", "monthly_token_budget_usd",
        sa.Column("monthly_token_budget_usd", sa.Float, nullable=True),
    )
    _add_column_if_missing(
        "agents", "tokens_used_today_usd",
        sa.Column("tokens_used_today_usd", sa.Float, nullable=False, server_default="0.0"),
    )
    _add_column_if_missing(
        "agents", "tokens_used_month_usd",
        sa.Column("tokens_used_month_usd", sa.Float, nullable=False, server_default="0.0"),
    )
    _add_column_if_missing(
        "agents", "budget_reset_at",
        sa.Column("budget_reset_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "agents", "auto_paused_reason",
        sa.Column("auto_paused_reason", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "auto_paused_reason")
    op.drop_column("agents", "budget_reset_at")
    op.drop_column("agents", "tokens_used_month_usd")
    op.drop_column("agents", "tokens_used_today_usd")
    op.drop_column("agents", "monthly_token_budget_usd")
    op.drop_column("agents", "daily_token_budget_usd")
    op.drop_index("idx_notifications_read_created", table_name="notifications")
    op.drop_index("idx_notifications_created_at", table_name="notifications")
    op.drop_index("idx_agent_messages_created_at", table_name="agent_messages")
    op.drop_index("idx_agent_logs_created_at", table_name="agent_logs")
    op.drop_index("idx_system_logs_created_at", table_name="system_logs")
