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


DEFAULT_PERMISSIONS = {
    "trade_execute": False,
    "trade_approve": False,
    "trade_view": True,
    "positions_view": True,
    "positions_close": False,
    "sources_manage": False,
    "sources_view": True,
    "accounts_manage": False,
    "accounts_view": True,
    "messages_view": True,
    "analytics_view": True,
    "system_config": False,
    "admin_users": False,
    "admin_access": False,
    "kill_switch": False,
}

ADMIN_PERMISSIONS = {k: True for k in DEFAULT_PERMISSIONS}

ROLE_PRESETS = {
    "viewer": {
        **DEFAULT_PERMISSIONS,
    },
    "trader": {
        **DEFAULT_PERMISSIONS,
        "trade_execute": True,
        "trade_approve": True,
        "positions_close": True,
        "sources_manage": True,
        "accounts_manage": True,
    },
    "manager": {
        **DEFAULT_PERMISSIONS,
        "trade_execute": True,
        "trade_approve": True,
        "positions_close": True,
        "sources_manage": True,
        "accounts_manage": True,
        "system_config": True,
        "admin_users": True,
    },
    "admin": ADMIN_PERMISSIONS,
}


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(100), nullable=True)
    timezone = Column(String(50), nullable=False, default="UTC")
    notification_prefs = Column(JSONB, nullable=False, default=lambda: {"email_enabled": True})
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    role = Column(String(30), nullable=False, default="trader")
    permissions = Column(JSONB, nullable=False, default=lambda: dict(DEFAULT_PERMISSIONS))
    email_verified = Column(Boolean, nullable=False, default=False)
    email_verification_token = Column(String(255), nullable=True)
    email_verification_expires = Column(DateTime(timezone=True), nullable=True)
    mfa_secret = Column(String(255), nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    trading_accounts = relationship("TradingAccount", back_populates="user", cascade="all, delete-orphan")
    data_sources = relationship("DataSource", back_populates="user", cascade="all, delete-orphan")

    def has_permission(self, perm: str) -> bool:
        if self.is_admin:
            return True
        perms = self.permissions or {}
        return bool(perms.get(perm, DEFAULT_PERMISSIONS.get(perm, False)))


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
    server_id = Column(String(100), nullable=True)
    server_name = Column(String(200), nullable=True)
    data_purpose = Column(String(20), nullable=False, default="trades")
    enabled = Column(Boolean, nullable=False, default=True)
    connection_status = Column(String(20), nullable=False, default="DISCONNECTED")
    last_connected_at = Column(DateTime(timezone=True), nullable=True)
    linked_strategy_id = Column(UUID(as_uuid=True), nullable=True)
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
    guild_id = Column(String(100), nullable=True)
    guild_name = Column(String(200), nullable=True)
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


class TradePipeline(Base):
    __tablename__ = "trade_pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    data_source_id = Column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id = Column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trading_account_id = Column(
        UUID(as_uuid=True), ForeignKey("trading_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enabled = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default="STOPPED")
    error_message = Column(Text, nullable=True)
    auto_approve = Column(Boolean, nullable=False, default=True)
    paper_mode = Column(Boolean, nullable=False, default=False)
    pipeline_type = Column(String(20), nullable=False, default="trade")
    trigger_config = Column(JSONB, nullable=False, default=dict)
    market_hours_mode = Column(String(20), nullable=False, default="regular_only")
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    messages_count = Column(Integer, nullable=False, default=0)
    trades_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User")
    data_source = relationship("DataSource")
    channel = relationship("Channel")
    trading_account = relationship("TradingAccount")

    __table_args__ = (
        UniqueConstraint("channel_id", "trading_account_id", name="uq_pipeline_channel_account"),
        Index("idx_pipeline_user", "user_id"),
        Index("idx_pipeline_source", "data_source_id"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trading_account_id = Column(UUID(as_uuid=True), ForeignKey("trading_accounts.id"), nullable=True)
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


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=True)
    data_source_id = Column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    channel_id = Column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trading_account_id = Column(
        UUID(as_uuid=True), ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    summary = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("idx_backtest_run_user", "user_id", "created_at"),)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id = Column(
        UUID(as_uuid=True), ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    ticker = Column(String(10), nullable=False)
    strike = Column(Numeric(10, 2), nullable=False)
    option_type = Column(String(4), nullable=False)
    expiration = Column(DateTime, nullable=True)
    action = Column(String(4), nullable=False)
    quantity = Column(String(20), nullable=False)
    entry_price = Column(Numeric(10, 2), nullable=False)
    exit_price = Column(Numeric(10, 2), nullable=True)
    entry_ts = Column(DateTime(timezone=True), nullable=False)
    exit_ts = Column(DateTime(timezone=True), nullable=True)
    exit_reason = Column(String(20), nullable=True)
    realized_pnl = Column(Numeric(12, 2), nullable=True)
    raw_message = Column(Text, nullable=True)

    __table_args__ = (Index("idx_backtest_trade_run", "backtest_run_id"),)


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


class BoardTask(Base):
    __tablename__ = "board_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="refinement")
    priority = Column(String(20), nullable=False, default="medium")
    position = Column(Integer, nullable=False, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    labels = Column(JSONB, nullable=False, default=list)
    due_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_board_task_status", "status", "position"),
    )


# ── Phase 2 Models ──────────────────────────────────────────────────────────


class UserWatchlist(Base):
    __tablename__ = "user_watchlist"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
        Index("idx_watchlist_user", "user_id"),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    model_type = Column(String(30), nullable=False)  # sentiment, llm, strategy, option_analyzer
    provider = Column(String(30), nullable=False)  # finbert, ollama, custom
    model_identifier = Column(String(200), nullable=False)  # ProsusAI/finbert, mistral, etc.
    version = Column(String(30), nullable=True)
    description = Column(Text, nullable=True)
    config = Column(JSONB, nullable=False, default=dict)
    input_schema = Column(JSONB, nullable=True)
    output_schema = Column(JSONB, nullable=True)
    status = Column(String(20), nullable=False, default="available")  # available, downloading, error, disabled
    health_status = Column(String(20), nullable=False, default="unknown")
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    performance_metrics = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class SentimentMessage(Base):
    __tablename__ = "sentiment_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    data_source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True)
    channel_name = Column(String(200), nullable=True)
    author = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    ticker = Column(String(10), nullable=True, index=True)
    sentiment_label = Column(String(20), nullable=True)  # Very Bullish..Very Bearish
    sentiment_score = Column(Numeric(6, 4), nullable=True)  # -1.0 to 1.0
    confidence = Column(Numeric(5, 4), nullable=True)
    source_message_id = Column(String(100), nullable=True)
    raw_metadata = Column(JSONB, nullable=False, default=dict)
    message_timestamp = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_sentiment_msg_ticker", "ticker", "created_at"),
        Index("idx_sentiment_msg_user", "user_id", "created_at"),
    )


class TickerSentiment(Base):
    __tablename__ = "ticker_sentiment"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(10), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    sentiment_label = Column(String(20), nullable=False)
    sentiment_score = Column(Numeric(6, 4), nullable=False)
    message_count = Column(Integer, nullable=False, default=0)
    bullish_count = Column(Integer, nullable=False, default=0)
    bearish_count = Column(Integer, nullable=False, default=0)
    neutral_count = Column(Integer, nullable=False, default=0)
    mention_change_pct = Column(Numeric(8, 2), nullable=True)
    sources = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "period_start", name="uq_ticker_sentiment_period"),
        Index("idx_ticker_sentiment_time", "period_start", "period_end"),
    )


class SentimentAlert(Base):
    __tablename__ = "sentiment_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(10), nullable=True)
    alert_type = Column(String(30), nullable=False)  # threshold, flip, spike
    config = Column(JSONB, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class NewsHeadline(Base):
    __tablename__ = "news_headlines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_api = Column(String(30), nullable=False)  # finnhub, newsapi, reddit, etc.
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    author = Column(String(200), nullable=True)
    tickers = Column(JSONB, nullable=False, default=list)  # ["AAPL", "MSFT"]
    category = Column(String(50), nullable=True)
    sentiment_label = Column(String(20), nullable=True)
    sentiment_score = Column(Numeric(6, 4), nullable=True)
    importance_score = Column(Numeric(5, 2), nullable=True)
    cluster_id = Column(String(100), nullable=True, index=True)
    cluster_size = Column(Integer, nullable=False, default=1)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_news_created", "created_at"),
        Index("idx_news_source", "source_api", "created_at"),
        Index("idx_news_cluster", "cluster_id"),
    )


class NewsConnection(Base):
    __tablename__ = "news_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_api = Column(String(30), nullable=False)
    display_name = Column(String(100), nullable=False)
    api_key_encrypted = Column(LargeBinary, nullable=True)
    config = Column(JSONB, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    last_poll_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "source_api", name="uq_news_conn_user_source"),
    )


class AdvancedPipeline(Base):
    __tablename__ = "advanced_pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    flow_json = Column(JSONB, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="draft")  # draft, active, paused, error
    version = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    tags = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("idx_adv_pipeline_user", "user_id"),)


class AdvancedPipelineVersion(Base):
    __tablename__ = "advanced_pipeline_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(
        UUID(as_uuid=True), ForeignKey("advanced_pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)
    flow_json = Column(JSONB, nullable=False, default=dict)
    change_summary = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("pipeline_id", "version", name="uq_pipeline_version"),
    )


class StrategyModel(Base):
    __tablename__ = "strategy_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    strategy_text = Column(Text, nullable=False)
    parsed_config = Column(JSONB, nullable=False, default=dict)
    features = Column(JSONB, nullable=False, default=list)
    backtest_summary = Column(JSONB, nullable=True)
    status = Column(String(20), nullable=False, default="draft")  # draft, backtesting, ready, deployed, failed
    deployed_pipeline_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class OptionAnalysisLog(Base):
    __tablename__ = "option_analysis_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker = Column(String(10), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # bullish/bearish
    input_context = Column(JSONB, nullable=False, default=dict)
    recommended_contracts = Column(JSONB, nullable=False, default=list)
    multi_leg_suggestions = Column(JSONB, nullable=False, default=list)
    gex_snapshot = Column(JSONB, nullable=True)
    rationale = Column(Text, nullable=True)
    outcome = Column(JSONB, nullable=True)
    user_feedback = Column(String(20), nullable=True)  # good, bad, neutral
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("idx_option_analysis_ticker", "ticker", "created_at"),)


class AITradeDecision(Base):
    __tablename__ = "ai_trade_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    pipeline_id = Column(UUID(as_uuid=True), nullable=True)
    trigger_type = Column(String(30), nullable=False)  # sentiment, news, strategy
    trigger_data = Column(JSONB, nullable=False, default=dict)
    ticker = Column(String(10), nullable=True)
    decision = Column(String(20), nullable=False)  # trade, skip, manual_confirm
    decision_rationale = Column(Text, nullable=True)
    trade_params = Column(JSONB, nullable=True)
    option_analysis_id = Column(UUID(as_uuid=True), nullable=True)
    trade_id = Column(UUID(as_uuid=True), nullable=True)
    outcome = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_ai_decision_user", "user_id", "created_at"),
        Index("idx_ai_decision_ticker", "ticker", "created_at"),
    )
