"""
Agent, AgentBacktest, and AgentLog models. M1.6, M2.3, M2.4.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # trading | trend
    engine_type: Mapped[str] = mapped_column(String(20), nullable=False, default="sdk")  # sdk | pipeline
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CREATED")
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    phoenix_api_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    worker_container_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    worker_status: Mapped[str] = mapped_column(String(30), nullable=False, default="STOPPED")

    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    channel_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    analyst_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_signal_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_trade_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    current_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="conservative")
    rules_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Phase 4: Supervisor agent staged improvements requiring user approval
    pending_improvements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_research_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Phase H7: Token budget tracking + enforcement
    daily_token_budget_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    monthly_token_budget_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tokens_used_today_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tokens_used_month_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    budget_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_paused_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Phase 4 (agents-tab-fix): latest backtest/Claude SDK error for fast list reads
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Phase P: runtime status + heartbeat-derived activity marker
    runtime_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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
    current_step: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strategy_template: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    equity_curve: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_selection: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    backtesting_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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


class PipelineWorkerState(Base):
    """Per-agent pipeline worker state for cursor tracking and stats."""
    __tablename__ = "pipeline_worker_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    stream_key: Mapped[str] = mapped_column(String(200), nullable=False)
    last_cursor: Mapped[str] = mapped_column(String(50), nullable=False, default="0-0")
    signals_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_executed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    portfolio_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
