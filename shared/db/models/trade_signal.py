"""Trade signal logging for RL feedback loop.

Every decision the agent makes (execute/reject/watchlist/paper) is logged
here with its feature snapshot. At EOD, we enrich each row with actual
outcome prices and flag `was_missed_opportunity` for rejected signals that
would have been profitable. This feeds the next retraining cycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class TradeSignal(Base):
    __tablename__ = "trade_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    signal_source: Mapped[str] = mapped_column(String(30), nullable=False, default="discord")
    source_message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Model decision
    predicted_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # decision values: 'executed', 'rejected', 'watchlist', 'paper'
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Feature snapshot at decision time (~30 key features for RL feedback)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Outcome (filled at EOD)
    outcome_price_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_price_4h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_price_eod: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    was_missed_opportunity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Analyst agent fields
    analyst_persona: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool_signals_used: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    risk_reward_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pattern_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
