"""
AgentSession model — tracks Claude Code agent sessions for the Agent Gateway.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False, default="backtester")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="starting")
    working_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Position sub-agent fields (Phase 1.3)
    parent_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    position_ticker: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    position_side: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    session_role: Mapped[str] = mapped_column(String(30), nullable=False, default="primary")
    # session_role: 'primary' | 'position_monitor' | 'research' | 'supervisor'
    # Phase 4 (agents-tab-fix): paper vs live mode recorded per session
    trading_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="live")

    # Runtime visibility fields (Phase 5.1)
    host_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
