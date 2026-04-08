"""Unified system log model for all client, server, and agent logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # client | server | agent | backtest
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="INFO", index=True)  # DEBUG | INFO | WARN | ERROR
    service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # api | dashboard | agent-gateway | backtesting | etc
    agent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    backtest_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    step: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # for backtest pipeline steps
    progress_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-100
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
