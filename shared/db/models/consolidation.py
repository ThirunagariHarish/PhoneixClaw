"""
ConsolidationRun model — tracks nightly consolidation pipeline runs (Phase 3).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class ConsolidationRun(Base):
    """Record of a single nightly/weekly/manual consolidation pipeline run for an agent."""

    __tablename__ = "consolidation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="nightly"
    )  # nightly | weekly | manual
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending | running | completed | failed
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trades_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wiki_entries_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wiki_entries_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wiki_entries_pruned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    patterns_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rules_proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consolidation_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
