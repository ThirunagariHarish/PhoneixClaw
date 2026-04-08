"""pm phase15 prediction markets expansion

Revision ID: 033_pm_phase15
Revises: 032
Create Date: 2026-04-07

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "033_pm_phase15"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pm_top_bets
    op.create_table(
        "pm_top_bets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pm_markets.id"), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False, server_default="robinhood_predictions"),
        sa.Column("recommendation_date", sa.Date(), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("confidence_score", sa.SmallInteger(), nullable=False),
        sa.Column("edge_bps", sa.SmallInteger(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("accepted_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pm_orders.id"), nullable=True),
        sa.Column("bull_argument", sa.Text(), nullable=True),
        sa.Column("bear_argument", sa.Text(), nullable=True),
        sa.Column("debate_summary", sa.Text(), nullable=True),
        sa.Column("bull_score", sa.SmallInteger(), nullable=True),
        sa.Column("bear_score", sa.SmallInteger(), nullable=True),
        sa.Column("sample_probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("consensus_spread", sa.Float(), nullable=True),
        sa.Column("reference_class", sa.String(64), nullable=True),
        sa.Column("base_rate_yes", sa.Float(), nullable=True),
        sa.Column("base_rate_sample_size", sa.Integer(), nullable=True),
        sa.Column("base_rate_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("market_id", "recommendation_date", name="uq_pm_top_bets_market_date"),
    )
    op.create_index("ix_pm_top_bets_date_status", "pm_top_bets", ["recommendation_date", "status"])
    op.create_index("ix_pm_top_bets_market_date", "pm_top_bets", ["market_id", "recommendation_date"])
    op.create_index("uq_pm_top_bets_market_venue", "pm_top_bets", ["market_id", "venue"], unique=True)

    # pm_chat_messages
    op.create_table(
        "pm_chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("bet_recommendation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("accepted_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pm_orders.id"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_pm_chat_messages_session_created", "pm_chat_messages", ["session_id", "created_at"])
    op.create_index("ix_pm_chat_messages_created_at", "pm_chat_messages", [sa.text("created_at DESC")])

    # pm_agent_activity_log
    op.create_table(
        "pm_agent_activity_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("markets_scanned_today", sa.Integer(), nullable=True),
        sa.Column("bets_generated_today", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_pm_activity_log_agent_created", "pm_agent_activity_log", ["agent_type", "created_at"])
    op.create_index("ix_pm_activity_log_severity_created", "pm_agent_activity_log", ["severity", "created_at"])

    # pm_strategy_research_log
    op.create_table(
        "pm_strategy_research_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sources_queried", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_findings", sa.Text(), nullable=False),
        sa.Column("proposed_config_delta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("applied_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_pm_research_log_run_at", "pm_strategy_research_log", ["run_at"])
    op.create_index("ix_pm_research_log_applied_run_at", "pm_strategy_research_log", ["applied", "run_at"])

    # pm_historical_markets
    op.create_table(
        "pm_historical_markets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("venue_market_id", sa.String(255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("outcomes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("winning_outcome", sa.String(255), nullable=True),
        sa.Column("resolution_date", sa.Date(), nullable=True),
        sa.Column("price_history_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("community_discussion_summary", sa.Text(), nullable=True),
        sa.Column("volume_usd", sa.Float(), nullable=True),
        sa.Column("liquidity_peak_usd", sa.Float(), nullable=True),
        sa.Column("reference_class", sa.String(64), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("venue", "venue_market_id", name="uq_pm_historical_markets_venue_id"),
    )
    op.create_index("ix_pm_historical_markets_reference_class", "pm_historical_markets", ["reference_class"])
    op.create_index("ix_pm_historical_markets_venue", "pm_historical_markets", ["venue"])

    # pm_market_embeddings
    op.create_table(
        "pm_market_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "historical_market_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pm_historical_markets.id"),
            nullable=False,
        ),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_pm_market_embeddings_historical_market_id", "pm_market_embeddings", ["historical_market_id"])

    # pm_model_evaluations
    op.create_table(
        "pm_model_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("brier_score", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("accuracy", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("sharpe_proxy", sa.Float(), nullable=True),
        sa.Column("num_markets_tested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("evaluated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("pm_model_evaluations")
    op.drop_table("pm_market_embeddings")
    op.drop_table("pm_historical_markets")
    op.drop_table("pm_strategy_research_log")
    op.drop_table("pm_agent_activity_log")
    op.drop_table("pm_chat_messages")
    op.drop_table("pm_top_bets")
