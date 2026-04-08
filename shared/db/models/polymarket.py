"""
Polymarket v1.0 ORM models.

Phase 1 of the Polymarket tab feature. See:
- docs/prd/polymarket-tab.md
- docs/architecture/polymarket-tab.md  (sections 4.1 - 4.8)

All tables are PM-specific (prefixed `pm_`). They reference the existing
`strategies`, `users`, and `backtests` tables. Audit rows in
`pm_promotion_audit` are intended to be immutable; the repository layer
must not expose UPDATE/DELETE operations on them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.db.models.base import Base


class PMMarket(Base):
    """Discovery snapshot + metadata for a single prediction-market market (4.1)."""

    __tablename__ = "pm_markets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    venue: Mapped[str] = mapped_column(String(20), nullable=False, default="polymarket", index=True)
    venue_market_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    outcomes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liquidity_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expiry: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    oracle_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PMStrategy(Base):
    """PM-specific strategy config and runtime state (4.2)."""

    __tablename__ = "pm_strategies"
    __table_args__ = (
        CheckConstraint("mode IN ('PAPER','LIVE')", name="ck_pm_strategies_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    archetype: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="PAPER")
    bankroll_usd: Mapped[float] = mapped_column(Float, nullable=False, default=5000.0)
    max_strategy_notional_usd: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    max_trade_notional_usd: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    kelly_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    min_edge_bps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_promotion_attempt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    paper_mode_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    last_successful_backtest_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PMOrder(Base):
    """One PM order (paper or live), possibly part of an arb leg group (4.3)."""

    __tablename__ = "pm_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_strategies.id", ondelete="RESTRICT"), nullable=False
    )
    pm_market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_markets.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_token_id: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    qty_shares: Mapped[float] = mapped_column(Float, nullable=False)
    limit_price: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    venue_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fees_paid_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f9_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    jurisdiction_attestation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pm_jurisdiction_attestations.id", ondelete="SET NULL"),
        nullable=True,
    )
    arb_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PMPosition(Base):
    """Open or closed PM position per (strategy, market, outcome, mode) (4.4)."""

    __tablename__ = "pm_positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False
    )
    pm_market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_markets.id", ondelete="CASCADE"), nullable=False
    )
    outcome_token_id: Mapped[str] = mapped_column(String(128), nullable=False)
    qty_shares: Mapped[float] = mapped_column(Float, nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    unrealized_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PMCalibrationSnapshot(Base):
    """Daily calibration snapshot per strategy/category (4.5)."""

    __tablename__ = "pm_calibration_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    n_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    log_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reliability_bins: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PMResolutionScore(Base):
    """F9 resolution-risk score per market (4.6)."""

    __tablename__ = "pm_resolution_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_markets.id", ondelete="CASCADE"), nullable=False
    )
    oracle_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    prior_disputes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_ambiguity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tradeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    model_version: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)


class PMPromotionAudit(Base):
    """Immutable audit row for any promote/demote/attempt/block (4.7)."""

    __tablename__ = "pm_promotion_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_strategies.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    gate_evaluations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attached_backtest_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    jurisdiction_attestation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pm_jurisdiction_attestations.id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    new_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PMJurisdictionAttestation(Base):
    """Per-user jurisdiction attestation; required before live PM activity (4.8)."""

    __tablename__ = "pm_jurisdiction_attestations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    attestation_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    acknowledged_geoblock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_at_attestation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PMTopBet(Base):
    __tablename__ = "pm_top_bets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pm_markets.id"), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, server_default="robinhood_predictions")
    recommendation_date: Mapped[date] = mapped_column(Date, nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    confidence_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    edge_bps: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accepted_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_orders.id"), nullable=True
    )
    # F-ACC-1: Debate Pipeline columns
    bull_argument: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bear_argument: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    debate_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bull_score: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    bear_score: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    # F-ACC-2: CoT Sampling columns
    sample_probabilities: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=None)
    consensus_spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # F-ACC-3: Reference Class columns
    reference_class: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    base_rate_yes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    base_rate_sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_rate_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("market_id", "recommendation_date", name="uq_pm_top_bets_market_date"),
        UniqueConstraint("market_id", "venue", name="uq_pm_top_bets_market_venue"),
        Index("ix_pm_top_bets_date_status", "recommendation_date", "status"),
        Index("ix_pm_top_bets_market_date", "market_id", "recommendation_date"),
    )


class PMChatMessage(Base):
    __tablename__ = "pm_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    bet_recommendation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    accepted_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_orders.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pm_chat_messages_session_created", "session_id", "created_at"),
    )


class PMAgentActivityLog(Base):
    __tablename__ = "pm_agent_activity_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)  # info | warn | error
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    markets_scanned_today: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bets_generated_today: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pm_activity_log_agent_created", "agent_type", "created_at"),
        Index("ix_pm_activity_log_severity_created", "severity", "created_at"),
    )


class PMStrategyResearchLog(Base):
    __tablename__ = "pm_strategy_research_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    sources_queried: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    raw_findings: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_config_delta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    applied_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    applied_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pm_research_log_run_at", "run_at"),
        Index("ix_pm_research_log_applied_run_at", "applied", "run_at"),
    )


class PMHistoricalMarket(Base):
    __tablename__ = "pm_historical_markets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    venue_market_id: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcomes_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    winning_outcome: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resolution_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    price_history_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    community_discussion_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    volume_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liquidity_peak_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reference_class: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("venue", "venue_market_id", name="uq_pm_historical_markets_venue_id"),
    )


class PMMarketEmbedding(Base):
    __tablename__ = "pm_market_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    historical_market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_historical_markets.id"), nullable=False
    )
    embedding: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class PMModelEvaluation(Base):
    __tablename__ = "pm_model_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sharpe_proxy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    num_markets_tested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
