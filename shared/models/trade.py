import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import JSON

JSONB = JSON().with_variant(PG_JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(100), nullable=True)
    timezone = Column(String(50), nullable=False, default="UTC")
    notification_prefs = Column(JSONB, nullable=False, default=lambda: {"email_enabled": True})
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    trading_accounts = relationship("TradingAccount", back_populates="user", cascade="all, delete-orphan")
    data_sources = relationship("DataSource", back_populates="user", cascade="all, delete-orphan")


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    broker_type = Column(String(30), nullable=False)
    display_name = Column(String(100), nullable=False)
    credentials_encrypted = Column(LargeBinary, nullable=False)
    paper_mode = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=True)
    risk_config = Column(
        JSONB,
        nullable=False,
        default=lambda: {
            "max_position_size": 10,
            "max_daily_loss": 1000,
            "max_total_contracts": 100,
            "max_notional_value": 50000,
        },
    )
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    health_status = Column(String(20), nullable=False, default="UNKNOWN")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="trading_accounts")
    mappings = relationship("AccountSourceMapping", back_populates="trading_account", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_ta_user_broker", "user_id", "broker_type"),)


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    display_name = Column(String(100), nullable=False)
    auth_type = Column(String(20), nullable=False, default="user_token")
    credentials_encrypted = Column(LargeBinary, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    connection_status = Column(String(20), nullable=False, default="DISCONNECTED")
    last_connected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="data_sources")
    channels = relationship("Channel", back_populates="data_source", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_ds_user_type", "user_id", "source_type"),)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data_source_id = Column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_identifier = Column(String(200), nullable=False)
    display_name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    data_source = relationship("DataSource", back_populates="channels")
    mappings = relationship("AccountSourceMapping", back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("data_source_id", "channel_identifier", name="uq_channel_per_source"),)


class AccountSourceMapping(Base):
    __tablename__ = "account_source_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trading_account_id = Column(
        UUID(as_uuid=True), ForeignKey("trading_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id = Column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    config_overrides = Column(JSONB, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    trading_account = relationship("TradingAccount", back_populates="mappings")
    channel = relationship("Channel", back_populates="mappings")

    __table_args__ = (UniqueConstraint("trading_account_id", "channel_id", name="uq_account_channel"),)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trading_account_id = Column(UUID(as_uuid=True), ForeignKey("trading_accounts.id"), nullable=False)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("channels.id"), nullable=True)
    ticker = Column(String(10), nullable=False)
    strike = Column(Numeric(10, 2), nullable=False)
    option_type = Column(String(4), nullable=False)
    expiration = Column(DateTime, nullable=True)
    action = Column(String(4), nullable=False)
    quantity = Column(String(20), nullable=False)
    resolved_quantity = Column(Integer, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    buffered_price = Column(Numeric(10, 2), nullable=True)
    fill_price = Column(Numeric(10, 2), nullable=True)
    source = Column(String(20), nullable=False, default="discord")
    source_message_id = Column(String(100), nullable=True)
    source_author = Column(String(100), nullable=True)
    raw_message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")
    rejection_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    broker_order_id = Column(String(100), nullable=True)
    profit_target = Column(Numeric(5, 4), nullable=False, default=0.30)
    stop_loss = Column(Numeric(5, 4), nullable=False, default=0.20)
    buffer_pct_used = Column(Numeric(5, 4), nullable=True)
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    close_reason = Column(String(20), nullable=True)
    realized_pnl = Column(Numeric(12, 2), nullable=True)
    execution_latency_ms = Column(Integer, nullable=True)
    slippage_pct = Column(Numeric(5, 4), nullable=True)

    __table_args__ = (
        Index("idx_trades_user", "user_id"),
        Index("idx_trades_account", "trading_account_id"),
        Index("idx_trades_status", "user_id", "status"),
        Index("idx_trades_ticker", "ticker", "strike", "option_type", "expiration"),
        Index("idx_trades_created", "user_id", "created_at"),
        Index("idx_trades_source", "source", "created_at"),
    )


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trading_account_id = Column(UUID(as_uuid=True), ForeignKey("trading_accounts.id"), nullable=False)
    ticker = Column(String(10), nullable=False)
    strike = Column(Numeric(10, 2), nullable=False)
    option_type = Column(String(4), nullable=False)
    expiration = Column(DateTime, nullable=False)
    quantity = Column(Integer, nullable=False)
    avg_entry_price = Column(Numeric(10, 2), nullable=False)
    total_cost = Column(Numeric(12, 2), nullable=False)
    profit_target = Column(Numeric(5, 4), nullable=False, default=0.30)
    stop_loss = Column(Numeric(5, 4), nullable=False, default=0.20)
    high_water_mark = Column(Numeric(10, 2), nullable=True)
    broker_symbol = Column(String(50), nullable=False)
    status = Column(String(10), nullable=False, default="OPEN")
    opened_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    close_reason = Column(String(20), nullable=True)
    close_price = Column(Numeric(10, 2), nullable=True)
    realized_pnl = Column(Numeric(12, 2), nullable=True)
    last_updated = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_positions_user", "user_id"),
        Index("idx_positions_account", "trading_account_id"),
        Index("idx_positions_status", "user_id", "status"),
        Index("idx_positions_ticker", "ticker"),
    )


class TradeEvent(Base):
    __tablename__ = "trade_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    trade_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)
    event_data = Column(JSONB, nullable=False, default=dict)
    source_service = Column(String(30), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("idx_trade_events_type", "event_type", "created_at"),)


class DailyMetrics(Base):
    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trading_account_id = Column(UUID(as_uuid=True), ForeignKey("trading_accounts.id"), nullable=False)
    date = Column(Date, nullable=False)
    total_trades = Column(Integer, default=0)
    executed_trades = Column(Integer, default=0)
    rejected_trades = Column(Integer, default=0)
    errored_trades = Column(Integer, default=0)
    closed_positions = Column(Integer, default=0)
    total_pnl = Column(Numeric(12, 2), default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    avg_win_pct = Column(Numeric(5, 4), nullable=True)
    avg_loss_pct = Column(Numeric(5, 4), nullable=True)
    max_drawdown = Column(Numeric(12, 2), nullable=True)
    avg_execution_latency_ms = Column(Integer, nullable=True)
    avg_slippage_pct = Column(Numeric(5, 4), nullable=True)
    avg_buffer_used = Column(Numeric(5, 4), nullable=True)
    open_positions_eod = Column(Integer, default=0)
    portfolio_value = Column(Numeric(12, 2), nullable=True)
    buying_power = Column(Numeric(12, 2), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("trading_account_id", "date", name="uq_daily_account"),
        Index("idx_daily_metrics_user", "user_id", "date"),
        Index("idx_daily_metrics_account", "trading_account_id", "date"),
    )


class AnalystPerformance(Base):
    __tablename__ = "analyst_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), nullable=False)
    author = Column(String(100), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    total_signals = Column(Integer, default=0)
    executed_signals = Column(Integer, default=0)
    profitable_signals = Column(Integer, default=0)
    total_pnl = Column(Numeric(12, 2), default=0)
    avg_pnl_pct = Column(Numeric(5, 4), nullable=True)
    win_rate = Column(Numeric(5, 4), nullable=True)
    avg_holding_time_minutes = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Configuration(Base):
    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(JSONB, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_config"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    role = Column(String(10), nullable=False, default="user")
    trade_id = Column(UUID(as_uuid=True), ForeignKey("trades.trade_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("idx_chat_user_created", "user_id", "created_at"),)


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    data_source_id = Column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type = Column(String(20), nullable=False, default="discord")
    channel_name = Column(String(200), nullable=True)
    author = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    source_message_id = Column(String(100), nullable=True)
    raw_metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_raw_msg_user_source", "user_id", "data_source_id"),
        Index("idx_raw_msg_created", "user_id", "created_at"),
    )


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    notification_type = Column(String(30), nullable=False)
    channel = Column(String(20), nullable=False)
    priority = Column(String(10), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    status = Column(String(10), nullable=False, default="SENT")
    read = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
