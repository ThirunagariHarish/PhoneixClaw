"""
BacktestTrade model — stores enriched trade data reconstructed during backtesting.
Each row represents one complete trade (entry + exit) with full market data enrichment.
"""

from __future__ import annotations
from typing import Optional

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backtest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_backtests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="long")  # long / short
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    holding_period_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    signal_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_messages.id", ondelete="SET NULL"), nullable=True
    )
    close_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_messages.id", ondelete="SET NULL"), nullable=True
    )

    # Technical enrichment at entry
    entry_rsi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_macd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_bollinger_position: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # -1 to 1
    entry_vwap_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_sma_20_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_sma_50_distance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # vs 20-day avg
    entry_atr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Market context
    market_vix: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_spy_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hour_of_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_pre_market: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_news_driven: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Options flow context
    option_flow_sentiment: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # bullish/bearish/neutral
    gex_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Classification
    is_profitable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pattern_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
