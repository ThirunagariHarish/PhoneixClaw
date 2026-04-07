"""Phase P sprint — agent_logs, agent_crons, agent runtime_status snapshot.

Revision ID: 027
Revises: 026
Create Date: 2026-04-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name=:n"),
        {"n": name},
    ).first())


def _has_column(table: str, col: str) -> bool:
    conn = op.get_bind()
    return bool(conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"),
        {"t": table, "c": col},
    ).first())


def upgrade() -> None:
    # --- agent_logs ----------------------------------------------------------
    if not _has_table("agent_logs"):
        op.create_table(
            "agent_logs",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("agent_id", sa.String(64), nullable=False, index=True),
            sa.Column("level", sa.String(16), nullable=False, server_default="info"),
            sa.Column("source", sa.String(64), nullable=True),
            sa.Column("message", sa.Text, nullable=False),
            sa.Column("context", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )
        op.create_index("ix_agent_logs_agent_time",
                        "agent_logs", ["agent_id", "created_at"])

    # --- agent_crons ---------------------------------------------------------
    if not _has_table("agent_crons"):
        op.create_table(
            "agent_crons",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("agent_id", sa.String(64), nullable=False, index=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("cron_expression", sa.String(64), nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False,
                      server_default="prompt"),
            sa.Column("action_payload", sa.JSON, nullable=True),
            sa.Column("enabled", sa.Boolean, nullable=False,
                      server_default=sa.text("TRUE")),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("run_count", sa.Integer, nullable=False,
                      server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("NOW()")),
        )

    # --- agents.runtime_status + last_activity_at ---------------------------
    if not _has_column("agents", "runtime_status"):
        op.add_column(
            "agents",
            sa.Column("runtime_status", sa.String(16), nullable=True),
        )
    if not _has_column("agents", "last_activity_at"):
        op.add_column(
            "agents",
            sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_table("agent_crons"):
        op.drop_table("agent_crons")
    if _has_table("agent_logs"):
        op.drop_table("agent_logs")
    if _has_column("agents", "runtime_status"):
        op.drop_column("agents", "runtime_status")
    if _has_column("agents", "last_activity_at"):
        op.drop_column("agents", "last_activity_at")
