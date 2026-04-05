"""Learning session model for tracking agent backtesting/learning runs."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_type: Mapped[str] = mapped_column(String(50), nullable=False, default="backtest")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", index=True)
    channel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision_val: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall_val: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    auc_roc: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
