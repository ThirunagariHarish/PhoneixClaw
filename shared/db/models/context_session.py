"""
ContextSession model — tracks smart context builder runs per chat/trading session (Phase 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class ContextSession(Base):
    """Record of a single smart context build for an agent session."""

    __tablename__ = "context_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    session_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="chat"
    )  # trading | chat | analysis
    signal_symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8000)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wiki_entries_injected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_injected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manifest_sections_injected: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True
    )
