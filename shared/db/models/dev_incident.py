"""
Dev Agent incident tracking model.

M3.1: Dev Agent.
Reference: PRD Section 3.11, ArchitecturePlan Section 4.
"""

from __future__ import annotations
from typing import Optional

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class DevIncident(Base):
    __tablename__ = "dev_incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DETECTED", index=True)
    target_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_service: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_taken: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    action_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    rl_reward: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rl_state: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    rl_action_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
