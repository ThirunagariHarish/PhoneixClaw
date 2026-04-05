"""Claude Code instance model for VPS management."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.db.models.base import Base

class ClaudeCodeInstance(Base):
    __tablename__ = "claude_code_instances"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_username: Mapped[str] = mapped_column(String(100), nullable=False, default="root")
    ssh_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ONLINE")
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, default="vps")
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    claude_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    agent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_offline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
