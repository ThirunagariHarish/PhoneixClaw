"""Add decision_trail JSONB column to agent_trades for full audit trail.

Revision ID: 038_decision_trail
Revises: 037_context_sessions
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "038_decision_trail"
down_revision = "037_context_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_trades", sa.Column("decision_trail", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("agent_trades", "decision_trail")
