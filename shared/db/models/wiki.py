"""
AgentWikiEntry and AgentWikiEntryVersion models — Agent Knowledge Wiki.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ARRAY, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base

VALID_WIKI_CATEGORIES = {
    "MARKET_PATTERNS",
    "SYMBOL_PROFILES",
    "STRATEGY_LEARNINGS",
    "MISTAKES",
    "WINNING_CONDITIONS",
    "SECTOR_NOTES",
    "MACRO_CONTEXT",
    "TRADE_OBSERVATION",
}


class AgentWikiEntry(Base):
    """Persistent knowledge entry written by an agent (or user) for an agent."""

    __tablename__ = "agent_wiki_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    symbols: Mapped[list] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    trade_ref_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}")
    created_by: Mapped[str] = mapped_column(String(10), nullable=False, default="agent")  # 'agent' | 'user'
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AgentWikiEntryVersion(Base):
    """Immutable version snapshot for AgentWikiEntry history."""

    __tablename__ = "agent_wiki_entry_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_wiki_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # 'agent' | 'user'
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    change_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
