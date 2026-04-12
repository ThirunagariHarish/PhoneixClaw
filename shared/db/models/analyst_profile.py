"""Analyst behavior profiles built from historical trade data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class AnalystProfile(Base):
    __tablename__ = "analyst_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analyst_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate_10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_rate_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_hold_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    median_exit_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_pnl_p25: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_pnl_p75: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_entry_hour: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_exit_hour: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    preferred_exit_dow: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    drawdown_tolerance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    conviction_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    post_earnings_sell_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    profile_data: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
