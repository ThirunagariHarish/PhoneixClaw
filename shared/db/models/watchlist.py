"""Watchlist model for paper trading mode.

In PAPER mode, the agent adds tickers to a Robinhood watchlist instead of
executing real trades. Each watchlist entry tracks the entry context so we
can compute simulated P&L.
"""

from __future__ import annotations
from typing import Optional

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="buy")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Entry context (snapshot at the time the signal was added)
    entry_price_at_add: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Simulated P&L (computed by paper_portfolio.py periodically)
    simulated_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    simulated_pnl_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Original signal context (model confidence, pattern matches, reasoning)
    signal_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    # status: 'open' | 'closed' | 'expired'

    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_price_update: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
