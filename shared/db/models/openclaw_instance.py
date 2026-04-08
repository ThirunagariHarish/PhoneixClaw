"""
DEPRECATED — V3 removed the VPS layer (migration 007_v3_remove_vps_add_workers.py).
This model is kept only for Alembic migration history. Do not use in new code.
"""
from __future__ import annotations
from typing import Optional

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class OpenClawInstance(Base):
    __tablename__ = "openclaw_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)  # WireGuard IP or hostname
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=18800)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ONLINE")  # ONLINE, DEGRADED, OFFLINE
    node_type: Mapped[str] = mapped_column(String(10), nullable=False, default="vps")  # vps | local
    auto_registered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_offline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
