"""
Trading account model — links broker accounts to users.

M1.6: Database Schema.
Reference: PRD Section 3.2, ArchitecturePlan Section 4.
"""

from __future__ import annotations
from typing import Optional

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    broker: Mapped[str] = mapped_column(String(30), nullable=False)  # alpaca | ibkr | tradier | robinhood
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="paper")  # paper | live
    broker_account_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    credentials_encrypted: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    buying_power: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_daily_loss_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    max_position_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
