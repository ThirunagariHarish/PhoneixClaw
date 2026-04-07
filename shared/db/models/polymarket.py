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

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class PMMarket(Base):
    """Discovery snapshot + metadata for a single prediction-market market (4.1)."""

    __tablename__ = "pm_markets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    venue: Mapped[str] = mapped_column(String(20), nullable=False, default="polymarket", index=True)
    venue_market_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    outcomes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oracle_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    min_edge_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_promotion_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    paper_mode_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    last_successful_backtest_at: Mapped[datetime | None] = mapped_column(
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
    venue_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fees_paid_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    f9_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    jurisdiction_attestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pm_jurisdiction_attestations.id", ondelete="SET NULL"),
        nullable=True,
    )
    arb_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    unrealized_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PMCalibrationSnapshot(Base):
    """Daily calibration snapshot per strategy/category (4.5)."""

    __tablename__ = "pm_calibration_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_strategies.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    n_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    reliability_bins: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PMResolutionScore(Base):
    """F9 resolution-risk score per market (4.6)."""

    __tablename__ = "pm_resolution_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_markets.id", ondelete="CASCADE"), nullable=False
    )
    oracle_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    prior_disputes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_ambiguity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tradeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    model_version: Mapped[str | None] = mapped_column(String(30), nullable=True)


class PMPromotionAudit(Base):
    """Immutable audit row for any promote/demote/attempt/block (4.7)."""

    __tablename__ = "pm_promotion_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pm_strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pm_strategies.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    gate_evaluations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attached_backtest_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    jurisdiction_attestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pm_jurisdiction_attestations.id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    new_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    ip_at_attestation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
