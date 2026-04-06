"""
Agent, AgentBacktest, and AgentLog models. M1.6, M2.3, M2.4.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # trading | trend
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CREATED")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    phoenix_api_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    worker_container_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    worker_status: Mapped[str] = mapped_column(String(30), nullable=False, default="STOPPED")

    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    channel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analyst_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_trade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    current_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="conservative")
    rules_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Phase 4: Supervisor agent staged improvements requiring user approval
    pending_improvements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_research_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AgentBacktest(Base):
    """Backtest run linked to an agent for lifecycle gating (M2.3/M2.4)."""
    __tablename__ = "agent_backtests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING", index=True)
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strategy_template: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    equity_curve: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_selection: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    backtesting_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AgentLog(Base):
    """Structured agent log entry (M2.5)."""
    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
