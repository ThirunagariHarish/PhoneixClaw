# Implementation Guide: Phoenix Trade Bot

**Version:** 1.0
**Date:** 2026-02-20
**Companion Documents:** [PRD.md](PRD.md) | [Architecture.md](Architecture.md)

---

## Table of Contents

1. [Implementation Phases Overview](#1-implementation-phases-overview)
2. [Phase 1: Repository Restructure](#2-phase-1-repository-restructure)
3. [Phase 2: Shared Libraries](#3-phase-2-shared-libraries)
4. [Phase 3: Kafka and PostgreSQL Integration](#4-phase-3-kafka-and-postgresql-integration)
5. [Phase 4: Auth Service and Multi-Tenancy](#5-phase-4-auth-service-and-multi-tenancy)
6. [Phase 5: Service Implementations](#6-phase-5-service-implementations)
7. [Phase 6: Account and Source Management](#7-phase-6-account-and-source-management)
8. [Phase 7: Dashboard Implementation](#8-phase-7-dashboard-implementation)
9. [Phase 8: Trade Storage and Persistence](#9-phase-8-trade-storage-and-persistence)
10. [Phase 9: Monitoring, Metrics, and Suggestions](#10-phase-9-monitoring-metrics-and-suggestions)
11. [Phase 10: Docker and Docker Compose](#11-phase-10-docker-and-docker-compose)
12. [Phase 11: Kubernetes Deployment](#12-phase-11-kubernetes-deployment)
13. [Phase 12: Agentic Extensions](#13-phase-12-agentic-extensions)
14. [Testing Strategy](#14-testing-strategy)
15. [Runbook](#15-runbook)

---

## 1. Implementation Phases Overview

```mermaid
gantt
    title Implementation Timeline
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d

    section Phase 1
    Repository Restructure         :p1, 2026-02-24, 3d

    section Phase 2
    Shared Libraries               :p2, after p1, 3d

    section Phase 3
    Kafka + PostgreSQL             :p3, after p2, 4d

    section Phase 4
    Auth + Multi-Tenancy           :p4, after p3, 4d

    section Phase 5
    Service Implementations        :p5, after p4, 7d

    section Phase 6
    Account + Source Management    :p6, after p5, 4d

    section Phase 7
    Dashboard                      :p7, after p6, 7d

    section Phase 8
    Trade Storage + Persistence    :p8, after p5, 3d

    section Phase 9
    Monitoring + Metrics           :p9, after p7, 4d

    section Phase 10
    Docker + Compose               :p10, after p1, 2d

    section Phase 11
    Kubernetes                     :p11, after p9, 5d

    section Phase 12
    Agentic Extensions             :p12, after p11, 7d
```

---

## 2. Phase 1: Repository Restructure

### 2.1 Target Directory Layout

Starting from the current monolith, restructure into:

```
phoenix-trade-bot/
├── shared/
│   ├── __init__.py
│   ├── schemas/
│   ├── models/
│   ├── broker/
│   ├── kafka_utils/
│   ├── config/
│   └── crypto/                  # Fernet encryption for credentials
├── services/
│   ├── auth-service/            # User registration, login, JWT
│   ├── source-orchestrator/     # Manages per-user ingestor workers
│   ├── discord-ingestor/
│   ├── twitter-ingestor/        # Twitter/X signal ingestor
│   ├── reddit-ingestor/         # Reddit signal ingestor
│   ├── trade-parser/
│   ├── trade-gateway/
│   ├── trade-executor/
│   ├── position-monitor/
│   ├── notification-service/
│   ├── api-gateway/
│   └── dashboard-ui/
├── k8s/
├── tests/
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── PRD.md
├── Architecture.md
└── Implementation.md
```

### 2.2 File Migration Map

| Current Location | New Location | Notes |
|-----------------|-------------|-------|
| `connectors/discord_connector.py` | `services/discord-ingestor/src/connector.py` | Remove legacy DB writes, add Kafka producer |
| `parsing/trade_parser.py` | `services/trade-parser/src/parser.py` | Keep regex logic intact |
| `parsing/parsing.py` | Archive to `legacy/` | Superseded by `trade_parser.py` |
| `services/message_parser_service.py` | `services/trade-parser/src/service.py` | Replace queue writer with Kafka producer |
| `services/execution_service.py` | `services/trade-executor/src/executor.py` | Replace queue reader with Kafka consumer |
| `services/trade_queue_writer.py` | Remove | Replaced by Kafka |
| `services/trade_queue_reader.py` | Remove | Replaced by Kafka |
| `trading/alpaca_client.py` | `shared/broker/alpaca_adapter.py` | Wrap in BrokerAdapter protocol |
| `trading/trade_validator.py` | `services/trade-executor/src/validator.py` | Keep validation logic |
| `trading/position_manager.py` | `services/trade-executor/src/position_manager.py` | Adapt to new Position model |
| `db/models.py` | `shared/models/` (split) | Split into trade.py, position.py, audit.py |
| `db/db_util.py` | `shared/models/database.py` | Switch from SQLite to PostgreSQL |
| `config/config_loader.py` | `shared/config/base_config.py` | Keep pattern, add Kafka configs |
| `config/settings.yaml` | `shared/config/defaults.yaml` | Reference only |
| `main.py` | Each service gets its own `main.py` | Entry points per service |

### 2.3 Migration Steps

```bash
# Step 1: Create new directories
mkdir -p shared/{schemas,models,broker,kafka_utils,config,crypto}
mkdir -p services/{auth-service,source-orchestrator,discord-ingestor,twitter-ingestor,reddit-ingestor,trade-parser,trade-gateway,trade-executor,position-monitor,notification-service,api-gateway,dashboard-ui}
for svc in auth-service source-orchestrator discord-ingestor twitter-ingestor reddit-ingestor trade-parser trade-gateway trade-executor position-monitor notification-service api-gateway; do
    mkdir -p "services/$svc/src"
    touch "services/$svc/"{main.py,requirements.txt,Dockerfile}
    touch "services/$svc/src/__init__.py"
done
mkdir -p k8s/{kafka,postgres,redis,services}
mkdir -p tests/{unit,integration,e2e}

# Step 2: Archive legacy code
mkdir -p legacy
cp parsing/parsing.py legacy/
cp services/trade_queue_writer.py legacy/
cp services/trade_queue_reader.py legacy/
cp services/run_message_parser.py legacy/
cp services/run_execution_service.py legacy/

# Step 3: Move shared code
cp db/models.py shared/models/
cp config/config_loader.py shared/config/base_config.py
cp config/settings.yaml shared/config/defaults.yaml

# Step 4: Copy service code to new locations
cp connectors/discord_connector.py services/discord-ingestor/src/connector.py
cp parsing/trade_parser.py services/trade-parser/src/parser.py
cp services/message_parser_service.py services/trade-parser/src/service.py
cp services/execution_service.py services/trade-executor/src/executor.py
cp trading/alpaca_client.py shared/broker/alpaca_adapter.py
cp trading/trade_validator.py services/trade-executor/src/validator.py
cp trading/position_manager.py services/trade-executor/src/position_manager.py
```

---

## 3. Phase 2: Shared Libraries

### 3.1 `shared/config/base_config.py`

The centralized configuration loader used by all services.

```python
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class KafkaConfig:
    bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    schema_registry_url: str = os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")
    consumer_group: str = os.getenv("KAFKA_CONSUMER_GROUP", "default-group")
    auto_offset_reset: str = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")


@dataclass
class DatabaseConfig:
    url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader")


@dataclass
class RedisConfig:
    url: str = os.getenv("REDIS_URL", "redis://localhost:6379")


@dataclass
class BrokerConfig:
    api_key: str = os.getenv("ALPACA_API_KEY", "")
    secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    paper: bool = os.getenv("ALPACA_PAPER", "true").lower() == "true"


@dataclass
class RiskConfig:
    max_position_size: int = int(os.getenv("MAX_POSITION_SIZE", "10"))
    max_total_contracts: int = int(os.getenv("MAX_TOTAL_CONTRACTS", "100"))
    max_notional_value: float = float(os.getenv("MAX_NOTIONAL_VALUE", "50000.0"))
    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "1000.0"))
    ticker_blacklist: list[str] = field(default_factory=lambda: [
        t.strip() for t in os.getenv("TICKER_BLACKLIST", "").split(",") if t.strip()
    ])
    enable_trading: bool = os.getenv("ENABLE_TRADING", "true").lower() == "true"
    dry_run_mode: bool = os.getenv("DRY_RUN_MODE", "false").lower() == "true"


@dataclass
class ExecutionConfig:
    buffer_percentage: float = float(os.getenv("BUFFER_PERCENTAGE", "0.15"))
    buffer_max_percentage: float = float(os.getenv("BUFFER_MAX_PERCENTAGE", "0.30"))
    buffer_min_price: float = float(os.getenv("BUFFER_MIN_PRICE", "0.01"))
    buffer_overrides: str = os.getenv("BUFFER_OVERRIDES", "{}")
    default_profit_target: float = float(os.getenv("DEFAULT_PROFIT_TARGET", "0.30"))
    default_stop_loss: float = float(os.getenv("DEFAULT_STOP_LOSS", "0.20"))


@dataclass
class MonitorConfig:
    poll_interval_seconds: int = int(os.getenv("MONITOR_POLL_INTERVAL_SECONDS", "5"))
    trailing_stop_enabled: bool = os.getenv("TRAILING_STOP_ENABLED", "false").lower() == "true"
    trailing_stop_offset: float = float(os.getenv("TRAILING_STOP_OFFSET", "0.10"))


@dataclass
class GatewayConfig:
    approval_mode: str = os.getenv("APPROVAL_MODE", "auto")
    approval_timeout_seconds: int = int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "300"))


@dataclass
class AppConfig:
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


config = AppConfig()
```

### 3.2 `shared/broker/adapter.py`

The broker abstraction protocol.

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class BrokerAdapter(Protocol):
    async def place_limit_order(
        self, symbol: str, qty: int, side: str, price: float
    ) -> str:
        """Place a limit order. Returns broker order ID."""
        ...

    async def place_bracket_order(
        self, symbol: str, qty: int, side: str, price: float,
        take_profit: float, stop_loss: float
    ) -> str:
        """Place a bracket order with take-profit and stop-loss legs."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        ...

    async def get_positions(self) -> list[dict]:
        """Get all open positions from the broker."""
        ...

    async def get_quote(self, symbol: str) -> dict:
        """Get current quote for a symbol. Returns {bid, ask, last, timestamp}."""
        ...

    async def get_account(self) -> dict:
        """Get account summary. Returns {buying_power, cash, equity, portfolio_value}."""
        ...

    def format_option_symbol(
        self, ticker: str, expiration: str, option_type: str, strike: float
    ) -> str:
        """Format option symbol in broker-specific format (e.g., OCC)."""
        ...
```

### 3.3 `shared/broker/alpaca_adapter.py`

Concrete implementation wrapping the existing `AlpacaClient`.

```python
import asyncio
import logging
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError
from shared.broker.adapter import BrokerAdapter
from shared.config.base_config import config

logger = logging.getLogger(__name__)


class AlpacaBrokerAdapter:
    """BrokerAdapter implementation for Alpaca."""

    def __init__(self):
        self.client = TradingClient(
            api_key=config.broker.api_key,
            secret_key=config.broker.secret_key,
            paper=config.broker.paper,
        )
        logger.info("Alpaca broker adapter initialized (paper=%s)", config.broker.paper)

    def format_option_symbol(
        self, ticker: str, expiration: str, option_type: str, strike: float
    ) -> str:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d")
        opt_char = "C" if option_type == "CALL" else "P"
        strike_str = f"{int(strike * 1000):08d}"
        return f"{ticker}{exp_date.strftime('%Y%m%d')}{opt_char}{strike_str}"

    async def place_limit_order(
        self, symbol: str, qty: int, side: str, price: float
    ) -> str:
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            limit_price=price,
            time_in_force=TimeInForce.DAY,
        )
        loop = asyncio.get_event_loop()
        order = await loop.run_in_executor(None, self.client.submit_order, request)
        logger.info("Order placed: %s %d %s @ %.2f (ID: %s)", side, qty, symbol, price, order.id)
        return str(order.id)

    async def place_bracket_order(
        self, symbol: str, qty: int, side: str, price: float,
        take_profit: float, stop_loss: float
    ) -> str:
        from alpaca.trading.requests import TakeProfitRequest, StopLossRequest
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            limit_price=price,
            time_in_force=TimeInForce.DAY,
            take_profit=TakeProfitRequest(limit_price=take_profit),
            stop_loss=StopLossRequest(stop_price=stop_loss),
        )
        loop = asyncio.get_event_loop()
        order = await loop.run_in_executor(None, self.client.submit_order, request)
        return str(order.id)

    async def cancel_order(self, order_id: str) -> bool:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.cancel_order_by_id, order_id)
            return True
        except APIError:
            return False

    async def get_positions(self) -> list[dict]:
        loop = asyncio.get_event_loop()
        positions = await loop.run_in_executor(None, self.client.get_all_positions)
        return [
            {
                "symbol": p.symbol,
                "qty": int(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
        ]

    async def get_quote(self, symbol: str) -> dict:
        from alpaca.data.requests import StockLatestQuoteRequest
        from alpaca.data.historical import StockHistoricalDataClient
        data_client = StockHistoricalDataClient(config.broker.api_key, config.broker.secret_key)
        loop = asyncio.get_event_loop()
        quote = await loop.run_in_executor(
            None, data_client.get_stock_latest_quote, StockLatestQuoteRequest(symbol_or_symbols=symbol)
        )
        q = quote[symbol]
        return {"bid": float(q.bid_price), "ask": float(q.ask_price), "last": float(q.ask_price)}

    async def get_account(self) -> dict:
        loop = asyncio.get_event_loop()
        account = await loop.run_in_executor(None, self.client.get_account)
        return {
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "equity": float(account.equity),
            "portfolio_value": float(account.portfolio_value),
        }
```

### 3.4 `shared/kafka_utils/producer.py`

Reusable async Kafka producer.

```python
import json
import logging
from aiokafka import AIOKafkaProducer
from shared.config.base_config import config

logger = logging.getLogger(__name__)


class KafkaProducerWrapper:
    def __init__(self):
        self._producer: AIOKafkaProducer | None = None

    async def start(self):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=config.kafka.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            enable_idempotence=True,
        )
        await self._producer.start()
        logger.info("Kafka producer started (servers=%s)", config.kafka.bootstrap_servers)

    async def send(self, topic: str, value: dict, key: str | None = None):
        if not self._producer:
            raise RuntimeError("Producer not started. Call start() first.")
        await self._producer.send_and_wait(topic, value=value, key=key)
        logger.debug("Produced to %s (key=%s)", topic, key)

    async def stop(self):
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")
```

### 3.5 `shared/kafka_utils/consumer.py`

Reusable async Kafka consumer.

```python
import json
import logging
from collections.abc import Callable, Awaitable
from aiokafka import AIOKafkaConsumer
from shared.config.base_config import config

logger = logging.getLogger(__name__)


class KafkaConsumerWrapper:
    def __init__(self, topic: str, group_id: str):
        self._topic = topic
        self._group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self):
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=config.kafka.bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset=config.kafka.auto_offset_reset,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=False,
        )
        await self._consumer.start()
        logger.info("Kafka consumer started (topic=%s, group=%s)", self._topic, self._group_id)

    async def consume(self, handler: Callable[[dict], Awaitable[None]]):
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")
        async for msg in self._consumer:
            try:
                await handler(msg.value)
                await self._consumer.commit()
            except Exception:
                logger.exception("Error processing message from %s (offset=%d)", self._topic, msg.offset)

    async def stop(self):
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")
```

### 3.6 `shared/models/database.py`

PostgreSQL connection setup, replacing the SQLite `db_util.py`.

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from shared.config.base_config import config

engine = create_async_engine(config.database.url, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    from shared.models.trade import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

### 3.7 `shared/models/trade.py`

SQLAlchemy models for the new multi-tenant schema (see Architecture.md Section 4.2 for full DDL).

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, DateTime, Date, Text,
    Index, Numeric, ForeignKey, LargeBinary, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


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
    risk_config = Column(JSONB, nullable=False, default=lambda: {
        "max_position_size": 10, "max_daily_loss": 1000,
        "max_total_contracts": 100, "max_notional_value": 50000,
    })
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    health_status = Column(String(20), nullable=False, default="UNKNOWN")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="trading_accounts")
    mappings = relationship("AccountSourceMapping", back_populates="trading_account", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ta_user_broker", "user_id", "broker_type"),
    )


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    display_name = Column(String(100), nullable=False)
    credentials_encrypted = Column(LargeBinary, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    connection_status = Column(String(20), nullable=False, default="DISCONNECTED")
    last_connected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="data_sources")
    channels = relationship("Channel", back_populates="data_source", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ds_user_type", "user_id", "source_type"),
    )


class Channel(Base):
    __tablename__ = "channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data_source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_identifier = Column(String(200), nullable=False)
    display_name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    data_source = relationship("DataSource", back_populates="channels")
    mappings = relationship("AccountSourceMapping", back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("data_source_id", "channel_identifier", name="uq_channel_per_source"),
    )


class AccountSourceMapping(Base):
    __tablename__ = "account_source_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trading_account_id = Column(UUID(as_uuid=True), ForeignKey("trading_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True)
    config_overrides = Column(JSONB, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    trading_account = relationship("TradingAccount", back_populates="mappings")
    channel = relationship("Channel", back_populates="mappings")

    __table_args__ = (
        UniqueConstraint("trading_account_id", "channel_id", name="uq_account_channel"),
    )


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
        Index("idx_trades_status_created", "user_id", "status", "created_at"),
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

    __table_args__ = (
        Index("idx_trade_events_type", "event_type", "created_at"),
    )


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

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_config"),
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
    metadata = Column(JSONB, nullable=True)
    status = Column(String(10), nullable=False, default="SENT")
    read = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
```

---

## 4. Phase 3: Kafka and PostgreSQL Integration

### 4.1 Docker Compose for Infrastructure

Create `docker-compose.dev.yml` for local development infrastructure.

```yaml
version: "3.9"

services:
  kafka:
    image: apache/kafka-native:3.8
    container_name: kafka
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_LOG_DIRS: /tmp/kraft-combined-logs
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
      KAFKA_NUM_PARTITIONS: 6
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  schema-registry:
    image: confluentinc/cp-schema-registry:7.6.0
    container_name: schema-registry
    depends_on:
      kafka:
        condition: service_healthy
    ports:
      - "8081:8081"
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: kafka:9092

  postgres:
    image: postgres:16-alpine
    container_name: postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: phoenixtrader
      POSTGRES_USER: phoenixtrader
      POSTGRES_PASSWORD: localdev
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U phoenixtrader"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

### 4.2 Kafka Topic Creation Script

```bash
#!/bin/bash
# scripts/create-topics.sh

KAFKA_BOOTSTRAP="localhost:9092"

declare -A TOPICS=(
    ["raw-messages"]=3
    ["parsed-trades"]=6
    ["approved-trades"]=6
    ["execution-results"]=6
    ["exit-signals"]=6
    ["notifications"]=3
)

for topic in "${!TOPICS[@]}"; do
    partitions=${TOPICS[$topic]}
    echo "Creating topic: $topic (partitions=$partitions)"
    docker exec kafka /opt/kafka/bin/kafka-topics.sh \
        --bootstrap-server "$KAFKA_BOOTSTRAP" \
        --create \
        --topic "$topic" \
        --partitions "$partitions" \
        --replication-factor 1 \
        --if-not-exists
done

echo "All topics created."
```

### 4.3 `.env.example`

```bash
# Discord
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_TARGET_CHANNELS=123456789,987654321

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
SCHEMA_REGISTRY_URL=http://localhost:8081

# Database
DATABASE_URL=postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader

# Redis
REDIS_URL=redis://localhost:6379

# Broker (Alpaca)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_PAPER=true

# Execution
BUFFER_PERCENTAGE=0.15
BUFFER_OVERRIDES={}
DRY_RUN_MODE=true
ENABLE_TRADING=true

# Risk
MAX_POSITION_SIZE=10
MAX_TOTAL_CONTRACTS=100
MAX_NOTIONAL_VALUE=50000.0
MAX_DAILY_LOSS=1000.0
TICKER_BLACKLIST=

# Monitor
DEFAULT_PROFIT_TARGET=0.30
DEFAULT_STOP_LOSS=0.20
MONITOR_POLL_INTERVAL_SECONDS=5
TRAILING_STOP_ENABLED=false
TRAILING_STOP_OFFSET=0.10

# Gateway
APPROVAL_MODE=auto
APPROVAL_TIMEOUT_SECONDS=300

# Auth
JWT_SECRET_KEY=your_jwt_secret_key_here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Credential Encryption
CREDENTIAL_ENCRYPTION_KEY=your_fernet_key_here

# Logging
LOG_LEVEL=INFO
```

---

## 5. Phase 4: Auth Service and Multi-Tenancy

### 5.1 `shared/crypto/credentials.py`

Fernet encryption utility for broker API keys and source tokens.

```python
import json
import os
from cryptography.fernet import Fernet

_FERNET_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")
if not _FERNET_KEY:
    raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be set")

_fernet = Fernet(_FERNET_KEY.encode())


def encrypt_credentials(data: dict) -> bytes:
    return _fernet.encrypt(json.dumps(data).encode())


def decrypt_credentials(token: bytes) -> dict:
    return json.loads(_fernet.decrypt(token).decode())
```

### 5.2 `services/auth-service/main.py`

```python
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
import bcrypt
from jose import jwt, JWTError
from sqlalchemy import select

from shared.models.database import AsyncSessionLocal, init_db
from shared.models.trade import User

logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TTL = timedelta(minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")))
REFRESH_TTL = timedelta(days=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7")))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None
    timezone: str = "UTC"


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    timezone: str
    created_at: datetime


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _create_token(user_id: str, email: str, token_type: str, ttl: timedelta) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": token_type,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + ttl,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> uuid.UUID:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return uuid.UUID(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Auth Service", lifespan=lifespan)


@app.post("/auth/register", response_model=UserResponse, status_code=201)
async def register(req: RegisterRequest):
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")
        user = User(
            email=req.email,
            password_hash=_hash_password(req.password),
            name=req.name,
            timezone=req.timezone,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return UserResponse(id=str(user.id), email=user.email, name=user.name,
                            timezone=user.timezone, created_at=user.created_at)


@app.post("/auth/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == form.username))
        user = result.scalar_one_or_none()
        if not user or not _verify_password(form.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")
        user.last_login = datetime.now(timezone.utc)
        await session.commit()
        return TokenResponse(
            access_token=_create_token(str(user.id), user.email, "access", ACCESS_TTL),
            refresh_token=_create_token(str(user.id), user.email, "refresh", REFRESH_TTL),
        )


@app.post("/auth/refresh", response_model=TokenResponse)
async def refresh(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Not a refresh token")
        return TokenResponse(
            access_token=_create_token(payload["sub"], payload["email"], "access", ACCESS_TTL),
            refresh_token=_create_token(payload["sub"], payload["email"], "refresh", REFRESH_TTL),
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@app.get("/auth/me", response_model=UserResponse)
async def me(user_id: uuid.UUID = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(id=str(user.id), email=user.email, name=user.name,
                            timezone=user.timezone, created_at=user.created_at)
```

### 5.3 JWT Middleware for API Gateway

Add this middleware to `services/api-gateway/src/middleware.py`. It extracts `user_id` from the JWT and injects it into the request state so all downstream handlers can use `request.state.user_id`.

```python
import os
import uuid
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from jose import jwt, JWTError

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

PUBLIC_PATHS = {"/auth/", "/health", "/docs", "/openapi.json"}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing authorization header")

        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            request.state.user_id = uuid.UUID(payload["sub"])
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return await call_next(request)
```

### 5.4 Tenant-Scoped Query Utility

All database queries use this helper to ensure `user_id` filtering is never forgotten.

```python
# shared/models/tenant.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


def scoped_query(model, user_id: uuid.UUID):
    return select(model).where(model.user_id == user_id)


async def get_by_id_scoped(session: AsyncSession, model, record_id: uuid.UUID, user_id: uuid.UUID):
    result = await session.execute(
        select(model).where(model.id == record_id, model.user_id == user_id)
    )
    return result.scalar_one_or_none()
```

---

## 6. Phase 5: Service Implementations

### 6.1 Discord Ingestor (`services/discord-ingestor/main.py`)

```python
import asyncio
import logging
import discord
from discord import Intents
from shared.config.base_config import config
from shared.kafka_utils.producer import KafkaProducerWrapper

logging.basicConfig(level=config.log_level)
logger = logging.getLogger("discord-ingestor")

intents = Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
producer = KafkaProducerWrapper()

TARGET_CHANNELS = [
    int(c) for c in
    os.getenv("DISCORD_TARGET_CHANNELS", "").split(",") if c.strip()
]


@client.event
async def on_ready():
    await producer.start()
    logger.info("Discord ingestor ready as %s", client.user)


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if message.channel.id not in TARGET_CHANNELS:
        return
    content = message.content.strip()
    if not content:
        return

    await producer.send(
        topic="raw-messages",
        key=str(message.channel.id),
        value={
            "message_id": str(message.id),
            "source": "DISCORD",
            "channel_id": str(message.channel.id),
            "author": str(message.author),
            "content": content,
            "timestamp": int(message.created_at.timestamp() * 1000),
            "metadata": {"guild": str(message.guild.id) if message.guild else None},
        },
    )
    logger.info("Published raw message from %s: %s", message.author, content[:80])


if __name__ == "__main__":
    import os
    client.run(os.getenv("DISCORD_BOT_TOKEN"))
```

### 6.2 Trade Parser (`services/trade-parser/main.py`)

```python
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from shared.config.base_config import config
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import TradeEvent
from services.trade_parser.src.parser import parse_trade_message

logging.basicConfig(level=config.log_level)
logger = logging.getLogger("trade-parser")


async def handle_raw_message(msg: dict):
    parsed = parse_trade_message(msg["content"])
    if not parsed["actions"]:
        return

    for action in parsed["actions"]:
        trade_id = str(uuid.uuid4())

        trade_event = {
            "trade_id": trade_id,
            "source_message_id": msg["message_id"],
            "source": msg["source"],
            "action": action["action"],
            "ticker": action["ticker"],
            "strike": action["strike"],
            "option_type": action["option_type"],
            "expiration": action.get("expiration"),
            "quantity": str(action.get("quantity", 1)),
            "is_percentage": action.get("is_percentage", False),
            "price": action["price"],
            "raw_message": msg["content"],
            "author": msg.get("author", "unknown"),
            "parsed_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        }

        await producer.send(topic="parsed-trades", key=action["ticker"], value=trade_event)

        async with AsyncSessionLocal() as session:
            event = TradeEvent(
                trade_id=uuid.UUID(trade_id),
                event_type="PARSED",
                event_data={"raw_message": msg["content"], "source": msg["source"], "author": msg.get("author")},
                source_service="trade-parser",
            )
            session.add(event)
            await session.commit()

        logger.info("Parsed trade: %s %s %s%.0f%s @ %.2f",
                     trade_id[:8], action["action"], action["ticker"],
                     action["strike"], action["option_type"][0], action["price"])


producer = KafkaProducerWrapper()
consumer = KafkaConsumerWrapper(topic="raw-messages", group_id="trade-parser-group")


async def main():
    await producer.start()
    await consumer.start()
    logger.info("Trade parser started")
    await consumer.consume(handle_raw_message)


if __name__ == "__main__":
    asyncio.run(main())
```

### 6.3 Trade Gateway (`services/trade-gateway/main.py`)

```python
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from shared.config.base_config import config
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade, TradeEvent

logging.basicConfig(level=config.log_level)
logger = logging.getLogger("trade-gateway")

producer = KafkaProducerWrapper()
consumer = KafkaConsumerWrapper(topic="parsed-trades", group_id="trade-gateway-group")


async def handle_parsed_trade(msg: dict):
    trade_id = uuid.UUID(msg["trade_id"])

    async with AsyncSessionLocal() as session:
        trade = Trade(
            trade_id=trade_id,
            ticker=msg["ticker"],
            strike=msg["strike"],
            option_type=msg["option_type"],
            expiration=datetime.strptime(msg["expiration"], "%Y-%m-%d") if msg.get("expiration") else None,
            action=msg["action"],
            quantity=msg["quantity"],
            price=msg["price"],
            source=msg.get("source", "discord").lower(),
            source_message_id=msg.get("source_message_id"),
            source_author=msg.get("author"),
            raw_message=msg.get("raw_message"),
            status="PENDING",
            profit_target=config.execution.default_profit_target,
            stop_loss=config.execution.default_stop_loss,
        )
        session.add(trade)
        await session.commit()

    if config.gateway.approval_mode == "auto":
        async with AsyncSessionLocal() as session:
            from sqlalchemy import update
            await session.execute(
                update(Trade).where(Trade.trade_id == trade_id).values(
                    status="APPROVED", approved_at=datetime.now(timezone.utc), approved_by="auto"
                )
            )
            event = TradeEvent(
                trade_id=trade_id, event_type="APPROVED",
                event_data={"mode": "auto"}, source_service="trade-gateway",
            )
            session.add(event)
            await session.commit()

        await producer.send(
            topic="approved-trades", key=msg["ticker"],
            value={**msg, "status": "APPROVED", "profit_target": config.execution.default_profit_target,
                   "stop_loss": config.execution.default_stop_loss},
        )
        logger.info("Auto-approved trade %s", str(trade_id)[:8])
    else:
        await producer.send(
            topic="notifications", key="TRADE_PENDING",
            value={
                "notification_id": str(uuid.uuid4()),
                "type": "TRADE_PENDING",
                "priority": "NORMAL",
                "title": f"Pending: {msg['action']} {msg['ticker']} {msg['strike']}{msg['option_type'][0]}",
                "body": f"Trade {str(trade_id)[:8]} awaiting approval. Price: ${msg['price']}",
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            },
        )
        logger.info("Trade %s queued for manual approval", str(trade_id)[:8])


async def main():
    await producer.start()
    await consumer.start()
    logger.info("Trade gateway started (mode=%s)", config.gateway.approval_mode)
    await consumer.consume(handle_parsed_trade)


if __name__ == "__main__":
    asyncio.run(main())
```

### 6.4 Trade Executor (`services/trade-executor/src/buffer_pricing.py`)

```python
import json
import logging
from shared.config.base_config import config

logger = logging.getLogger(__name__)


def calculate_buffered_price(action: str, price: float, ticker: str) -> tuple[float, float]:
    """
    Calculate the limit price with buffer applied.

    Returns (buffered_price, effective_buffer_percentage).
    """
    overrides = json.loads(config.execution.buffer_overrides)
    buffer_pct = overrides.get(ticker, config.execution.buffer_percentage)
    buffer_pct = min(buffer_pct, config.execution.buffer_max_percentage)

    if action == "BUY":
        buffered = price * (1 + buffer_pct)
    else:
        buffered = price * (1 - buffer_pct)

    buffered = max(buffered, config.execution.buffer_min_price)
    buffered = round(buffered, 2)

    logger.info(
        "Buffer pricing: %s %s @ %.2f -> %.2f (buffer=%.1f%%)",
        action, ticker, price, buffered, buffer_pct * 100,
    )
    return buffered, buffer_pct
```

### 6.5 Trade Executor (`services/trade-executor/main.py`)

```python
import asyncio
import uuid
import logging
import time
from datetime import datetime, timezone
from sqlalchemy import update, select
from shared.config.base_config import config
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.broker.alpaca_adapter import AlpacaBrokerAdapter
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade, Position, TradeEvent
from services.trade_executor.src.buffer_pricing import calculate_buffered_price

logging.basicConfig(level=config.log_level)
logger = logging.getLogger("trade-executor")

broker = AlpacaBrokerAdapter()
producer = KafkaProducerWrapper()
approved_consumer = KafkaConsumerWrapper(topic="approved-trades", group_id="trade-executor-group")
exit_consumer = KafkaConsumerWrapper(topic="exit-signals", group_id="trade-executor-exit-group")


async def handle_approved_trade(msg: dict):
    trade_id = uuid.UUID(msg["trade_id"])
    start_time = time.monotonic()

    if not config.risk.enable_trading:
        await _reject_trade(trade_id, "Trading is disabled (kill switch)")
        return

    ticker = msg["ticker"]
    if ticker.upper() in [t.upper() for t in config.risk.ticker_blacklist]:
        await _reject_trade(trade_id, f"Ticker {ticker} is blacklisted")
        return

    quantity_str = str(msg["quantity"])
    is_percentage = msg.get("is_percentage", "%" in quantity_str)
    quantity = int(quantity_str.replace("%", "")) if not is_percentage else 1

    if is_percentage and msg["action"] == "SELL":
        pct = float(quantity_str.replace("%", ""))
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Position).where(
                    Position.ticker == ticker, Position.status == "OPEN",
                    Position.strike == msg["strike"], Position.option_type == msg["option_type"]
                )
            )
            position = result.scalar_one_or_none()
            if not position:
                await _reject_trade(trade_id, "No open position for percentage sell")
                return
            quantity = max(1, int(position.quantity * pct / 100))

    buffered_price, buffer_pct = calculate_buffered_price(msg["action"], msg["price"], ticker)

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Trade).where(Trade.trade_id == trade_id).values(
                status="PROCESSING", buffered_price=buffered_price,
                buffer_pct_used=buffer_pct, resolved_quantity=quantity,
            )
        )
        await session.commit()

    if config.risk.dry_run_mode:
        logger.info("[DRY RUN] Would execute: %s %d %s @ %.2f (buffered)", msg["action"], quantity, ticker, buffered_price)
        await _mark_executed(trade_id, "DRY_RUN", buffered_price, None, start_time, msg)
        return

    symbol = broker.format_option_symbol(ticker, msg["expiration"], msg["option_type"], msg["strike"])
    try:
        order_id = await broker.place_limit_order(symbol, quantity, msg["action"], buffered_price)
    except Exception as e:
        await _mark_error(trade_id, str(e), msg)
        return

    if not order_id:
        await _mark_error(trade_id, "Broker returned no order ID", msg)
        return

    await _mark_executed(trade_id, order_id, buffered_price, None, start_time, msg)
    await _update_position(msg, quantity, buffered_price, symbol)


async def handle_exit_signal(msg: dict):
    logger.info("Exit signal for position %s: %s", msg["position_id"], msg["action"])
    ticker = msg["ticker"]
    symbol = broker.format_option_symbol(ticker, msg["expiration"], msg["option_type"], msg["strike"])
    try:
        order_id = await broker.place_limit_order(symbol, msg["quantity"], "SELL", msg["current_price"])
        logger.info("Exit order placed: %s (order=%s)", msg["action"], order_id)
    except Exception:
        logger.exception("Failed to place exit order for position %s", msg["position_id"])


async def _reject_trade(trade_id: uuid.UUID, reason: str):
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Trade).where(Trade.trade_id == trade_id).values(
                status="REJECTED", rejection_reason=reason,
                processed_at=datetime.now(timezone.utc),
            )
        )
        session.add(TradeEvent(
            trade_id=trade_id, event_type="REJECTED",
            event_data={"reason": reason}, source_service="trade-executor",
        ))
        await session.commit()
    logger.warning("Trade %s rejected: %s", str(trade_id)[:8], reason)


async def _mark_executed(trade_id, order_id, buffered_price, fill_price, start_time, msg):
    latency_ms = int((time.monotonic() - start_time) * 1000)
    slippage = abs(buffered_price - msg["price"]) / msg["price"] if msg["price"] > 0 else 0

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Trade).where(Trade.trade_id == trade_id).values(
                status="EXECUTED", broker_order_id=str(order_id),
                fill_price=fill_price or buffered_price,
                processed_at=datetime.now(timezone.utc),
                execution_latency_ms=latency_ms, slippage_pct=slippage,
            )
        )
        session.add(TradeEvent(
            trade_id=trade_id, event_type="EXECUTED",
            event_data={"order_id": str(order_id), "buffered_price": float(buffered_price),
                        "latency_ms": latency_ms, "slippage_pct": float(slippage)},
            source_service="trade-executor",
        ))
        await session.commit()

    await producer.send(topic="execution-results", key=str(trade_id), value={
        "trade_id": str(trade_id), "order_id": str(order_id), "status": "EXECUTED",
        **{k: msg[k] for k in ("action", "ticker", "strike", "option_type", "expiration")},
        "quantity": msg.get("resolved_quantity", msg["quantity"]),
        "requested_price": msg["price"], "buffered_price": float(buffered_price),
        "profit_target": msg.get("profit_target", config.execution.default_profit_target),
        "stop_loss": msg.get("stop_loss", config.execution.default_stop_loss),
        "executed_at": int(datetime.now(timezone.utc).timestamp() * 1000),
    })


async def _mark_error(trade_id, error, msg):
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Trade).where(Trade.trade_id == trade_id).values(
                status="ERROR", error_message=error, processed_at=datetime.now(timezone.utc),
            )
        )
        session.add(TradeEvent(
            trade_id=trade_id, event_type="ERROR",
            event_data={"error": error}, source_service="trade-executor",
        ))
        await session.commit()
    logger.error("Trade %s error: %s", str(trade_id)[:8], error)


async def _update_position(msg, quantity, price, symbol):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Position).where(
                Position.ticker == msg["ticker"], Position.status == "OPEN",
                Position.strike == msg["strike"], Position.option_type == msg["option_type"],
            )
        )
        position = result.scalar_one_or_none()

        if msg["action"] == "BUY":
            if position:
                old_qty = position.quantity
                new_qty = old_qty + quantity
                position.avg_entry_price = ((float(position.avg_entry_price) * old_qty) + (price * quantity)) / new_qty
                position.quantity = new_qty
                position.total_cost = float(position.avg_entry_price) * new_qty
            else:
                exp = datetime.strptime(msg["expiration"], "%Y-%m-%d") if msg.get("expiration") else None
                position = Position(
                    ticker=msg["ticker"], strike=msg["strike"], option_type=msg["option_type"],
                    expiration=exp, quantity=quantity, avg_entry_price=price,
                    total_cost=price * quantity, broker_symbol=symbol,
                    profit_target=msg.get("profit_target", config.execution.default_profit_target),
                    stop_loss=msg.get("stop_loss", config.execution.default_stop_loss),
                    high_water_mark=price,
                )
                session.add(position)
        elif msg["action"] == "SELL" and position:
            position.quantity -= quantity
            if position.quantity <= 0:
                position.status = "CLOSED"
                position.closed_at = datetime.now(timezone.utc)
                position.close_price = price
                position.realized_pnl = (price - float(position.avg_entry_price)) * quantity
                position.close_reason = "MANUAL"

        await session.commit()


async def main():
    await producer.start()
    await approved_consumer.start()
    await exit_consumer.start()
    logger.info("Trade executor started (dry_run=%s, trading=%s)", config.risk.dry_run_mode, config.risk.enable_trading)
    await asyncio.gather(
        approved_consumer.consume(handle_approved_trade),
        exit_consumer.consume(handle_exit_signal),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

### 6.6 Position Monitor (`services/position-monitor/main.py`)

```python
import asyncio
import uuid
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from shared.config.base_config import config
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.broker.alpaca_adapter import AlpacaBrokerAdapter
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Position

logging.basicConfig(level=config.log_level)
logger = logging.getLogger("position-monitor")

broker = AlpacaBrokerAdapter()
producer = KafkaProducerWrapper()
consumer = KafkaConsumerWrapper(topic="execution-results", group_id="position-monitor-group")


async def monitor_loop():
    while True:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Position).where(Position.status == "OPEN"))
                positions = list(result.scalars().all())

            if not positions:
                await asyncio.sleep(config.monitor.poll_interval_seconds)
                continue

            for pos in positions:
                try:
                    quote = await broker.get_quote(pos.broker_symbol)
                    current_price = quote.get("last", quote.get("ask", 0))
                    if current_price <= 0:
                        continue

                    entry = float(pos.avg_entry_price)
                    pnl_pct = (current_price - entry) / entry if entry > 0 else 0

                    exit_action = None
                    if pnl_pct >= float(pos.profit_target):
                        exit_action = "TAKE_PROFIT"
                    elif pnl_pct <= -float(pos.stop_loss):
                        exit_action = "STOP_LOSS"
                    elif config.monitor.trailing_stop_enabled and pos.high_water_mark:
                        hwm = float(pos.high_water_mark)
                        if current_price > hwm:
                            async with AsyncSessionLocal() as session:
                                await session.execute(
                                    update(Position).where(Position.id == pos.id)
                                    .values(high_water_mark=current_price)
                                )
                                await session.commit()
                        elif hwm > 0 and (hwm - current_price) / hwm >= config.monitor.trailing_stop_offset:
                            exit_action = "TRAILING_STOP"

                    exp = pos.expiration
                    if exp and isinstance(exp, datetime) and exp.date() <= datetime.now(timezone.utc).date():
                        exit_action = "EXPIRATION"

                    if exit_action:
                        await producer.send(
                            topic="exit-signals", key=str(pos.id),
                            value={
                                "position_id": pos.id,
                                "trade_id": str(uuid.uuid4()),
                                "ticker": pos.ticker,
                                "strike": float(pos.strike),
                                "option_type": pos.option_type,
                                "expiration": pos.expiration.strftime("%Y-%m-%d") if pos.expiration else None,
                                "action": exit_action,
                                "quantity": pos.quantity,
                                "entry_price": entry,
                                "current_price": current_price,
                                "pnl_percentage": round(pnl_pct, 4),
                                "signal_time": int(datetime.now(timezone.utc).timestamp() * 1000),
                            },
                        )
                        logger.info(
                            "Exit signal: %s for %s %s%.0f%s (PnL=%.1f%%)",
                            exit_action, pos.ticker, pos.ticker,
                            float(pos.strike), pos.option_type[0], pnl_pct * 100,
                        )
                except Exception:
                    logger.exception("Error monitoring position %d", pos.id)

        except Exception:
            logger.exception("Error in monitor loop")

        await asyncio.sleep(config.monitor.poll_interval_seconds)


async def main():
    await producer.start()
    await consumer.start()
    logger.info("Position monitor started (poll=%ds, PT=%.0f%%, SL=%.0f%%)",
                config.monitor.poll_interval_seconds,
                config.execution.default_profit_target * 100,
                config.execution.default_stop_loss * 100)
    await asyncio.gather(monitor_loop(), consumer.consume(lambda msg: asyncio.sleep(0)))


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 7. Phase 6: Account and Source Management

### 7.1 Trading Account CRUD API

Add to `services/api-gateway/src/routes/accounts.py`:

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from shared.models.database import AsyncSessionLocal
from shared.models.trade import TradingAccount
from shared.models.tenant import scoped_query, get_by_id_scoped
from shared.crypto.credentials import encrypt_credentials, decrypt_credentials

router = APIRouter(prefix="/api/v1/accounts", tags=["Trading Accounts"])


class CreateAccountRequest(BaseModel):
    broker_type: str
    display_name: str
    credentials: dict
    paper_mode: bool = True
    risk_config: dict | None = None


class AccountResponse(BaseModel):
    id: str
    broker_type: str
    display_name: str
    paper_mode: bool
    enabled: bool
    health_status: str
    risk_config: dict
    created_at: str


@router.get("")
async def list_accounts(request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        result = await session.execute(scoped_query(TradingAccount, user_id))
        accounts = result.scalars().all()
        return [AccountResponse(
            id=str(a.id), broker_type=a.broker_type, display_name=a.display_name,
            paper_mode=a.paper_mode, enabled=a.enabled, health_status=a.health_status,
            risk_config=a.risk_config, created_at=a.created_at.isoformat(),
        ) for a in accounts]


@router.post("", status_code=201)
async def create_account(req: CreateAccountRequest, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = TradingAccount(
            user_id=user_id,
            broker_type=req.broker_type.upper(),
            display_name=req.display_name,
            credentials_encrypted=encrypt_credentials(req.credentials),
            paper_mode=req.paper_mode,
            risk_config=req.risk_config or TradingAccount.risk_config.default.arg,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return {"id": str(account.id), "display_name": account.display_name}


@router.post("/{account_id}/test")
async def test_account(account_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = await get_by_id_scoped(session, TradingAccount, account_id, user_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        creds = decrypt_credentials(account.credentials_encrypted)
        # Instantiate the broker adapter dynamically and call get_account()
        from shared.broker.factory import create_broker_adapter
        adapter = create_broker_adapter(account.broker_type, creds, account.paper_mode)
        try:
            info = await adapter.get_account()
            account.health_status = "HEALTHY"
            await session.commit()
            return {"status": "healthy", "account_info": info}
        except Exception as e:
            account.health_status = "UNHEALTHY"
            await session.commit()
            return {"status": "unhealthy", "error": str(e)}


@router.post("/{account_id}/toggle-mode")
async def toggle_mode(account_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = await get_by_id_scoped(session, TradingAccount, account_id, user_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account.paper_mode = not account.paper_mode
        await session.commit()
        return {"id": str(account.id), "paper_mode": account.paper_mode}


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = await get_by_id_scoped(session, TradingAccount, account_id, user_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        await session.delete(account)
        await session.commit()
```

### 7.2 Data Source CRUD API

Add to `services/api-gateway/src/routes/sources.py`:

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.models.database import AsyncSessionLocal
from shared.models.trade import DataSource, Channel
from shared.models.tenant import scoped_query, get_by_id_scoped
from shared.crypto.credentials import encrypt_credentials

router = APIRouter(prefix="/api/v1/sources", tags=["Data Sources"])


class CreateSourceRequest(BaseModel):
    source_type: str
    display_name: str
    credentials: dict


class ChannelRequest(BaseModel):
    channel_identifier: str
    display_name: str


@router.get("")
async def list_sources(request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            scoped_query(DataSource, user_id).options(selectinload(DataSource.channels))
        )
        sources = result.scalars().all()
        return [{
            "id": str(s.id), "source_type": s.source_type, "display_name": s.display_name,
            "enabled": s.enabled, "connection_status": s.connection_status,
            "channels": [{"id": str(c.id), "identifier": c.channel_identifier,
                          "name": c.display_name, "enabled": c.enabled} for c in s.channels],
        } for s in sources]


@router.post("", status_code=201)
async def create_source(req: CreateSourceRequest, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        source = DataSource(
            user_id=user_id,
            source_type=req.source_type.upper(),
            display_name=req.display_name,
            credentials_encrypted=encrypt_credentials(req.credentials),
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        return {"id": str(source.id), "display_name": source.display_name}


@router.post("/{source_id}/test")
async def test_source(source_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        source = await get_by_id_scoped(session, DataSource, source_id, user_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        # TODO: implement per-source-type connectivity test
        return {"status": "connected", "source_type": source.source_type}


@router.get("/{source_id}/channels")
async def list_channels(source_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        source = await get_by_id_scoped(session, DataSource, source_id, user_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        result = await session.execute(select(Channel).where(Channel.data_source_id == source_id))
        channels = result.scalars().all()
        return [{"id": str(c.id), "identifier": c.channel_identifier,
                 "name": c.display_name, "enabled": c.enabled} for c in channels]


@router.post("/{source_id}/channels", status_code=201)
async def add_channel(source_id: uuid.UUID, req: ChannelRequest, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        source = await get_by_id_scoped(session, DataSource, source_id, user_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        channel = Channel(
            data_source_id=source_id,
            channel_identifier=req.channel_identifier,
            display_name=req.display_name,
        )
        session.add(channel)
        await session.commit()
        await session.refresh(channel)
        return {"id": str(channel.id), "identifier": channel.channel_identifier}
```

### 7.3 Account-Source Mapping API

Add to `services/api-gateway/src/routes/mappings.py`:

```python
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from shared.models.database import AsyncSessionLocal
from shared.models.trade import AccountSourceMapping, TradingAccount
from shared.models.tenant import get_by_id_scoped

router = APIRouter(prefix="/api/v1/accounts/{account_id}/mappings", tags=["Mappings"])


class CreateMappingRequest(BaseModel):
    channel_id: str
    config_overrides: dict | None = None


@router.get("")
async def list_mappings(account_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = await get_by_id_scoped(session, TradingAccount, account_id, user_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        result = await session.execute(
            select(AccountSourceMapping).where(AccountSourceMapping.trading_account_id == account_id)
        )
        mappings = result.scalars().all()
        return [{"id": str(m.id), "channel_id": str(m.channel_id),
                 "config_overrides": m.config_overrides, "enabled": m.enabled} for m in mappings]


@router.post("", status_code=201)
async def create_mapping(account_id: uuid.UUID, req: CreateMappingRequest, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = await get_by_id_scoped(session, TradingAccount, account_id, user_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        mapping = AccountSourceMapping(
            trading_account_id=account_id,
            channel_id=uuid.UUID(req.channel_id),
            config_overrides=req.config_overrides or {},
        )
        session.add(mapping)
        await session.commit()
        await session.refresh(mapping)
        return {"id": str(mapping.id), "channel_id": str(mapping.channel_id)}


@router.delete("/{mapping_id}", status_code=204)
async def delete_mapping(account_id: uuid.UUID, mapping_id: uuid.UUID, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        account = await get_by_id_scoped(session, TradingAccount, account_id, user_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        result = await session.execute(
            select(AccountSourceMapping).where(
                AccountSourceMapping.id == mapping_id,
                AccountSourceMapping.trading_account_id == account_id,
            )
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            raise HTTPException(status_code=404, detail="Mapping not found")
        await session.delete(mapping)
        await session.commit()
```

### 7.4 Broker Adapter Factory

`shared/broker/factory.py` creates a broker adapter from stored credentials rather than global env vars:

```python
from shared.broker.adapter import BrokerAdapter
from shared.broker.alpaca_adapter import AlpacaBrokerAdapter


def create_broker_adapter(broker_type: str, credentials: dict, paper_mode: bool) -> BrokerAdapter:
    if broker_type == "ALPACA":
        return AlpacaBrokerAdapter(
            api_key=credentials["api_key"],
            secret_key=credentials["secret_key"],
            paper=paper_mode,
        )
    raise ValueError(f"Unsupported broker: {broker_type}")
```

Update `AlpacaBrokerAdapter.__init__` to accept credentials as parameters instead of reading from global config:

```python
class AlpacaBrokerAdapter:
    def __init__(self, api_key: str = "", secret_key: str = "", paper: bool = True):
        self.client = TradingClient(
            api_key=api_key or config.broker.api_key,
            secret_key=secret_key or config.broker.secret_key,
            paper=paper,
        )
```

---

## 8. Phase 7: Dashboard Implementation

### 8.1 Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Framework | React 18+ with TypeScript | Component model, ecosystem |
| Build tool | Vite | Fast dev server, optimized builds |
| UI Library | Tailwind CSS + shadcn/ui | Modern, customizable components |
| Charts | Recharts | React-native charting, composable |
| Data fetching | TanStack Query (React Query) | Caching, auto-refresh, optimistic updates |
| WebSocket | Native WebSocket + reconnect logic | Real-time feeds |
| State | Zustand | Lightweight global state |
| Routing | React Router v6 | Standard SPA routing |

### 8.2 Dashboard Page Structure

```
dashboard-ui/
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   ├── context/
│   │   └── AuthContext.tsx           # JWT token management + auth state
│   ├── api/
│   │   ├── client.ts                # Axios instance with JWT interceptor
│   │   ├── auth.ts                  # Login, register, refresh
│   │   ├── accounts.ts              # Trading account CRUD
│   │   ├── sources.ts               # Data source CRUD
│   │   ├── mappings.ts              # Account-source mapping CRUD
│   │   ├── trades.ts                # Trade API calls
│   │   ├── positions.ts             # Position API calls
│   │   ├── metrics.ts               # Metrics/analytics API calls
│   │   ├── notifications.ts         # Notification center API
│   │   ├── config.ts                # Configuration API calls
│   │   └── websocket.ts             # WebSocket manager
│   ├── pages/
│   │   ├── auth/
│   │   │   ├── Login.tsx            # Email + password login form
│   │   │   └── Register.tsx         # Registration form
│   │   ├── dashboard/
│   │   │   ├── TradeMonitor.tsx     # Live trade feed + risk gauges
│   │   │   └── Positions.tsx        # Open/closed positions + exposure pie
│   │   ├── sources/
│   │   │   ├── SourceList.tsx       # Data source cards with status
│   │   │   ├── AddEditSource.tsx    # Create/edit source form
│   │   │   └── ChannelManager.tsx   # Enable/disable channels per source
│   │   ├── accounts/
│   │   │   ├── AccountList.tsx      # Account cards with paper/live badge
│   │   │   ├── AddEditAccount.tsx   # Create/edit account + risk config
│   │   │   └── SourceMapping.tsx    # Map channels to this account
│   │   ├── analytics/
│   │   │   ├── PnLAnalytics.tsx     # P&L charts, calendar heatmap
│   │   │   ├── AccountComparison.tsx # Side-by-side account P&L
│   │   │   ├── AnalystPerf.tsx      # Analyst leaderboard
│   │   │   └── Suggestions.tsx      # AI suggestions
│   │   └── system/
│   │       ├── SystemHealth.tsx     # Service health
│   │       ├── Notifications.tsx    # Notification center
│   │       └── Configuration.tsx    # Settings + kill switch
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx         # Main layout wrapper
│   │   │   ├── Sidebar.tsx          # Desktop sidebar nav
│   │   │   ├── BottomNav.tsx        # Mobile bottom tab bar
│   │   │   ├── Header.tsx           # Top bar with notification bell
│   │   │   └── ProtectedRoute.tsx   # Redirect to login if no JWT
│   │   ├── trades/
│   │   │   ├── TradeFeed.tsx
│   │   │   ├── TradeRow.tsx
│   │   │   ├── StatusBadge.tsx
│   │   │   ├── ApprovalActions.tsx
│   │   │   └── TradeReplayTimeline.tsx
│   │   ├── positions/
│   │   │   ├── PositionTable.tsx
│   │   │   ├── PositionHeatMap.tsx
│   │   │   └── PnLIndicator.tsx
│   │   ├── charts/
│   │   │   ├── CumulativePnL.tsx
│   │   │   ├── DailyPnLBars.tsx
│   │   │   ├── WinRateTrend.tsx
│   │   │   ├── DrawdownChart.tsx
│   │   │   ├── PnLByTicker.tsx
│   │   │   ├── PnLDistribution.tsx
│   │   │   ├── PnLCalendarHeatmap.tsx
│   │   │   ├── RiskGauges.tsx
│   │   │   ├── ExposurePieChart.tsx
│   │   │   ├── AccountComparisonChart.tsx
│   │   │   ├── StreakTracker.tsx
│   │   │   └── HoldingTimeChart.tsx
│   │   ├── metrics/
│   │   │   ├── StatCard.tsx
│   │   │   ├── StatusDonut.tsx
│   │   │   └── RejectionReasons.tsx
│   │   ├── sources/
│   │   │   ├── SourceCard.tsx
│   │   │   ├── SourceForm.tsx
│   │   │   └── ChannelToggle.tsx
│   │   ├── accounts/
│   │   │   ├── AccountCard.tsx
│   │   │   ├── AccountForm.tsx
│   │   │   ├── PaperLiveToggle.tsx
│   │   │   └── MappingEditor.tsx
│   │   ├── suggestions/
│   │   │   ├── SuggestionCard.tsx
│   │   │   └── ApplySuggestion.tsx
│   │   └── config/
│   │       ├── ConfigSection.tsx
│   │       ├── ConfigField.tsx
│   │       └── KillSwitch.tsx
│   └── hooks/
│       ├── useAuth.ts               # Login/logout/token refresh
│       ├── useMediaQuery.ts         # Responsive breakpoint detection
│       ├── useAccounts.ts           # Trading account data
│       ├── useSources.ts            # Data source data
│       ├── useTrades.ts
│       ├── usePositions.ts
│       ├── useMetrics.ts
│       ├── useWebSocket.ts
│       ├── useNotifications.ts
│       └── useConfig.ts
├── Dockerfile
├── nginx.conf
├── package.json
├── tailwind.config.ts
└── vite.config.ts
```

### 8.2a New Dashboard React Components

**Auth Context (`src/context/AuthContext.tsx`):**

```tsx
import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { login as apiLogin, register as apiRegister, refreshToken } from '../api/auth';

interface AuthState {
  isAuthenticated: boolean;
  accessToken: string | null;
  userId: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(
    localStorage.getItem('access_token')
  );
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    if (accessToken) {
      const payload = JSON.parse(atob(accessToken.split('.')[1]));
      setUserId(payload.sub);
    }
  }, [accessToken]);

  const login = async (email: string, password: string) => {
    const { access_token, refresh_token } = await apiLogin(email, password);
    localStorage.setItem('access_token', access_token);
    localStorage.setItem('refresh_token', refresh_token);
    setAccessToken(access_token);
  };

  const register = async (email: string, password: string, name?: string) => {
    await apiRegister(email, password, name);
    await login(email, password);
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setAccessToken(null);
    setUserId(null);
  };

  return (
    <AuthContext.Provider value={{
      isAuthenticated: !!accessToken,
      accessToken,
      userId,
      login,
      register,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
```

**Mobile-First Layout (`src/components/layout/AppShell.tsx`):**

```tsx
import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';
import { Header } from './Header';
import { useMediaQuery } from '../../hooks/useMediaQuery';

export function AppShell() {
  const isMobile = useMediaQuery('(max-width: 640px)');
  const isTablet = useMediaQuery('(max-width: 1024px)');
  const [sidebarOpen, setSidebarOpen] = useState(!isTablet);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <Header onMenuToggle={() => setSidebarOpen(!sidebarOpen)} />

      <div className="flex">
        {!isMobile && (
          <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        )}

        <main className={`flex-1 p-4 ${!isMobile && sidebarOpen ? 'ml-64' : ''} pb-20 sm:pb-4`}>
          <Outlet />
        </main>
      </div>

      {isMobile && <BottomNav />}
    </div>
  );
}
```

**Bottom Navigation (`src/components/layout/BottomNav.tsx`):**

```tsx
import { NavLink } from 'react-router-dom';
import {
  ChartBarIcon, ServerIcon, BanknotesIcon,
  ChartPieIcon, CogIcon
} from '@heroicons/react/24/outline';

const tabs = [
  { to: '/dashboard', icon: ChartBarIcon, label: 'Dashboard' },
  { to: '/sources', icon: ServerIcon, label: 'Sources' },
  { to: '/accounts', icon: BanknotesIcon, label: 'Accounts' },
  { to: '/analytics', icon: ChartPieIcon, label: 'Analytics' },
  { to: '/system', icon: CogIcon, label: 'System' },
];

export function BottomNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 z-50">
      <div className="flex justify-around">
        {tabs.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex flex-col items-center py-2 px-3 min-w-[64px] min-h-[44px]
               ${isActive ? 'text-blue-600' : 'text-gray-500'}`
            }
          >
            <Icon className="h-6 w-6" />
            <span className="text-xs mt-1">{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
```

**`useMediaQuery` Hook (`src/hooks/useMediaQuery.ts`):**

```tsx
import { useState, useEffect } from 'react';

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}
```

### 8.3 API Gateway Endpoints for Dashboard

These are the API endpoints the dashboard calls (implemented in `services/api-gateway/`).

#### Trades API

All queries are tenant-scoped via `request.state.user_id` (injected by JWT middleware).

```python
# services/api-gateway/src/routes/trades.py

from fastapi import APIRouter, Query, Request, HTTPException
from sqlalchemy import select, func
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade

router = APIRouter(prefix="/api/v1/trades", tags=["trades"])


@router.get("")
async def list_trades(
    request: Request,
    status: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    account_id: str | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        query = select(Trade).where(Trade.user_id == user_id).order_by(Trade.created_at.desc())
        if status:
            query = query.where(Trade.status == status.upper())
        if ticker:
            query = query.where(Trade.ticker == ticker.upper())
        if source:
            query = query.where(Trade.source == source.lower())
        if account_id:
            query = query.where(Trade.trading_account_id == account_id)
        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        trades = result.scalars().all()
    return {"trades": [_serialize_trade(t) for t in trades], "total": len(trades)}


@router.get("/{trade_id}")
async def get_trade(trade_id: str, request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade).where(Trade.trade_id == trade_id, Trade.user_id == user_id)
        )
        trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    return _serialize_trade(trade)
```

#### Metrics API

```python
# services/api-gateway/src/routes/metrics.py

from fastapi import APIRouter, Query, Request
from sqlalchemy import select, func, case
from datetime import date, timedelta
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade, Position, DailyMetrics, AnalystPerformance

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/daily")
async def get_daily_metrics(request: Request, account_id: str | None = None, range_days: int = Query(default=30, le=365)):
    user_id = request.state.user_id
    start_date = date.today() - timedelta(days=range_days)
    async with AsyncSessionLocal() as session:
        query = select(DailyMetrics).where(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= start_date,
        ).order_by(DailyMetrics.date)
        if account_id:
            query = query.where(DailyMetrics.trading_account_id == account_id)
        result = await session.execute(query)
        metrics = result.scalars().all()
    return {"metrics": [_serialize_daily(m) for m in metrics]}


@router.get("/trade-status")
async def get_trade_status_counts(request: Request):
    user_id = request.state.user_id
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade.status, func.count(Trade.id))
            .where(Trade.user_id == user_id)
            .group_by(Trade.status)
        )
        counts = {row[0]: row[1] for row in result.all()}
    return {"status_counts": counts}


@router.get("/pnl")
async def get_pnl_summary(request: Request, account_id: str | None = None, range_days: int = 30):
    user_id = request.state.user_id
    start_date = date.today() - timedelta(days=range_days)
    async with AsyncSessionLocal() as session:
        query = select(DailyMetrics.date, DailyMetrics.total_pnl).where(
            DailyMetrics.user_id == user_id,
            DailyMetrics.date >= start_date,
        ).order_by(DailyMetrics.date)
        if account_id:
            query = query.where(DailyMetrics.trading_account_id == account_id)
        result = await session.execute(query)
        rows = result.all()
    cumulative = 0
    data = []
    for row in rows:
        cumulative += float(row.total_pnl)
        data.append({"date": str(row.date), "daily_pnl": float(row.total_pnl), "cumulative_pnl": cumulative})
    return {"pnl": data}


@router.get("/rejection-reasons")
async def get_rejection_reasons(request: Request):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade.rejection_reason, func.count(Trade.id))
            .where(Trade.status == "REJECTED")
            .group_by(Trade.rejection_reason)
            .order_by(func.count(Trade.id).desc())
        )
        reasons = [{"reason": row[0] or "Unknown", "count": row[1]} for row in result.all()]
    return {"reasons": reasons}


@router.get("/win-rate")
async def get_win_rate(range_days: int = 30):
    start_date = date.today() - timedelta(days=range_days)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DailyMetrics.date, DailyMetrics.winning_trades, DailyMetrics.losing_trades)
            .where(DailyMetrics.date >= start_date)
            .order_by(DailyMetrics.date)
        )
        rows = result.all()
    data = []
    for row in rows:
        total = row.winning_trades + row.losing_trades
        rate = row.winning_trades / total if total > 0 else 0
        data.append({"date": str(row.date), "win_rate": round(rate, 4), "total": total})
    return {"win_rate": data}


@router.get("/analysts")
async def get_analyst_performance():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AnalystPerformance).order_by(AnalystPerformance.win_rate.desc())
        )
        analysts = result.scalars().all()
    return {"analysts": [_serialize_analyst(a) for a in analysts]}


@router.get("/latency")
async def get_execution_latency(range_days: int = 7):
    start_date = date.today() - timedelta(days=range_days)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade.execution_latency_ms)
            .where(Trade.status == "EXECUTED", Trade.created_at >= start_date)
            .where(Trade.execution_latency_ms.isnot(None))
        )
        latencies = [row[0] for row in result.all()]
    if not latencies:
        return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "count": 0}
    latencies.sort()
    n = len(latencies)
    return {
        "avg": sum(latencies) // n,
        "p50": latencies[n // 2],
        "p95": latencies[int(n * 0.95)],
        "p99": latencies[int(n * 0.99)],
        "count": n,
    }
```

#### Suggestions API

```python
# services/api-gateway/src/routes/suggestions.py

from fastapi import APIRouter
from sqlalchemy import select, func
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade, Position

router = APIRouter(prefix="/api/v1/suggestions", tags=["suggestions"])


@router.get("")
async def get_suggestions():
    suggestions = []

    async with AsyncSessionLocal() as session:
        # Buffer optimization
        result = await session.execute(
            select(
                func.avg(Trade.slippage_pct).label("avg_slippage"),
                func.avg(Trade.buffer_pct_used).label("avg_buffer"),
                func.count(Trade.id).label("count"),
            ).where(Trade.status == "EXECUTED", Trade.slippage_pct.isnot(None))
        )
        row = result.one_or_none()
        if row and row.count > 20:
            avg_slippage = float(row.avg_slippage or 0)
            avg_buffer = float(row.avg_buffer or 0)
            if avg_buffer > 0 and avg_slippage < avg_buffer * 0.5:
                recommended = round(max(avg_slippage * 2, 0.05), 2)
                suggestions.append({
                    "id": "buffer_opt",
                    "category": "buffer_optimization",
                    "severity": "info",
                    "title": "Buffer percentage may be too high",
                    "description": f"Average slippage is {avg_slippage:.1%} but buffer is {avg_buffer:.1%}. "
                                   f"Reducing buffer could save ~${(avg_buffer - recommended) * 480:.0f}/trade on a $4.80 option.",
                    "current_value": f"{avg_buffer:.2f}",
                    "recommended_value": f"{recommended:.2f}",
                    "confidence": min(0.95, row.count / 200),
                    "data_points": row.count,
                    "action": {"type": "config_change", "key": "BUFFER_PERCENTAGE", "value": str(recommended)},
                })

        # Win rate by time of day
        result = await session.execute(
            select(
                func.extract("hour", Trade.created_at).label("hour"),
                func.count(Trade.id).label("total"),
                func.sum(case((Trade.realized_pnl > 0, 1), else_=0)).label("wins"),
            )
            .where(Trade.status.in_(["EXECUTED", "CLOSED"]))
            .group_by("hour")
            .order_by("hour")
        )
        hourly = result.all()
        best_hour, best_rate = None, 0
        for h in hourly:
            if h.total >= 5:
                rate = h.wins / h.total
                if rate > best_rate:
                    best_rate = rate
                    best_hour = int(h.hour)
        if best_hour is not None and best_rate > 0.6:
            suggestions.append({
                "id": "timing_opt",
                "category": "timing_patterns",
                "severity": "info",
                "title": f"Best trading hour: {best_hour}:00",
                "description": f"Trades placed at {best_hour}:00 have a {best_rate:.0%} win rate. "
                               f"Consider focusing execution during this window.",
                "confidence": 0.7,
            })

        # Ticker concentration risk
        result = await session.execute(
            select(Position.ticker, func.count(Position.id), func.sum(Position.quantity))
            .where(Position.status == "OPEN")
            .group_by(Position.ticker)
        )
        tickers = result.all()
        total_qty = sum(t[2] for t in tickers)
        for t in tickers:
            concentration = t[2] / total_qty if total_qty > 0 else 0
            if concentration > 0.5:
                suggestions.append({
                    "id": f"concentration_{t[0]}",
                    "category": "risk_exposure",
                    "severity": "warning",
                    "title": f"High concentration in {t[0]}",
                    "description": f"{t[0]} represents {concentration:.0%} of open positions. "
                                   f"Consider diversifying to reduce single-ticker risk.",
                    "confidence": 0.9,
                })

    return {"suggestions": suggestions, "generated_at": datetime.now(timezone.utc).isoformat()}
```

#### Configuration API

```python
# services/api-gateway/src/routes/config.py

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Configuration
from shared.config.base_config import config

router = APIRouter(prefix="/api/v1/config", tags=["config"])

EDITABLE_KEYS = {
    "BUFFER_PERCENTAGE": {"type": "float", "min": 0.01, "max": 0.50, "category": "execution"},
    "BUFFER_OVERRIDES": {"type": "json", "category": "execution"},
    "DEFAULT_PROFIT_TARGET": {"type": "float", "min": 0.05, "max": 1.0, "category": "monitor"},
    "DEFAULT_STOP_LOSS": {"type": "float", "min": 0.05, "max": 1.0, "category": "monitor"},
    "TRAILING_STOP_ENABLED": {"type": "bool", "category": "monitor"},
    "TRAILING_STOP_OFFSET": {"type": "float", "min": 0.01, "max": 0.50, "category": "monitor"},
    "MONITOR_POLL_INTERVAL_SECONDS": {"type": "int", "min": 1, "max": 60, "category": "monitor"},
    "MAX_POSITION_SIZE": {"type": "int", "min": 1, "max": 100, "category": "risk"},
    "MAX_TOTAL_CONTRACTS": {"type": "int", "min": 1, "max": 1000, "category": "risk"},
    "MAX_NOTIONAL_VALUE": {"type": "float", "min": 1000, "max": 500000, "category": "risk"},
    "MAX_DAILY_LOSS": {"type": "float", "min": 100, "max": 50000, "category": "risk"},
    "TICKER_BLACKLIST": {"type": "list", "category": "risk"},
    "APPROVAL_MODE": {"type": "enum", "values": ["auto", "manual"], "category": "gateway"},
    "APPROVAL_TIMEOUT_SECONDS": {"type": "int", "min": 30, "max": 3600, "category": "gateway"},
    "DRY_RUN_MODE": {"type": "bool", "category": "execution"},
    "ENABLE_TRADING": {"type": "bool", "category": "execution"},
}


@router.get("")
async def get_config():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Configuration))
        configs = {c.key: c.value for c in result.scalars().all()}
    return {
        "config": {
            key: {"value": configs.get(key, _get_default(key)), "meta": meta}
            for key, meta in EDITABLE_KEYS.items()
        }
    }


@router.put("")
async def update_config(updates: dict):
    for key, value in updates.items():
        if key not in EDITABLE_KEYS:
            raise HTTPException(400, f"Key '{key}' is not editable")
    async with AsyncSessionLocal() as session:
        for key, value in updates.items():
            existing = await session.get(Configuration, key)
            if existing:
                existing.value = value
            else:
                session.add(Configuration(key=key, value=value, category=EDITABLE_KEYS[key]["category"]))
        await session.commit()
    return {"status": "updated", "keys": list(updates.keys())}


@router.post("/kill-switch")
async def toggle_kill_switch(enable: bool = False):
    async with AsyncSessionLocal() as session:
        existing = await session.get(Configuration, "ENABLE_TRADING")
        if existing:
            existing.value = enable
        else:
            session.add(Configuration(key="ENABLE_TRADING", value=enable, category="execution"))
        await session.commit()
    return {"trading_enabled": enable}
```

### 8.4 WebSocket Implementation

```python
# services/api-gateway/src/websocket.py

import asyncio
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade, Position

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {"trades": [], "positions": [], "notifications": []}

    async def connect(self, channel: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(channel, []).append(ws)

    def disconnect(self, channel: str, ws: WebSocket):
        if channel in self.active:
            self.active[channel] = [w for w in self.active[channel] if w != ws]

    async def broadcast(self, channel: str, data: dict):
        dead = []
        for ws in self.active.get(channel, []):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)


manager = ConnectionManager()


async def trades_ws(ws: WebSocket):
    await manager.connect("trades", ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect("trades", ws)


async def positions_ws(ws: WebSocket):
    await manager.connect("positions", ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect("positions", ws)
```

---

## 9. Phase 8: Trade Storage and Persistence

### 9.1 Storage Guarantee

Every trade that enters the system (via the parser) is **persisted in PostgreSQL** regardless of outcome. The `trades` table serves as the single source of truth for all trade lifecycle data.

### 9.2 What Happens at Each Stage

| Stage | DB Operation | Table | Status Set | Event Written |
|-------|-------------|-------|-----------|--------------|
| Message parsed into trade | INSERT | `trades` | PENDING | trade_events: PARSED |
| Trade auto-approved | UPDATE | `trades` | APPROVED | trade_events: APPROVED |
| Trade manually approved | UPDATE | `trades` | APPROVED | trade_events: APPROVED |
| Trade manually rejected | UPDATE | `trades` | REJECTED | trade_events: REJECTED |
| Trade timeout (no approval) | UPDATE | `trades` | REJECTED | trade_events: REJECTED |
| Executor picks up trade | UPDATE | `trades` | PROCESSING | trade_events: EXECUTING |
| Validation fails at executor | UPDATE | `trades` | REJECTED | trade_events: REJECTED |
| Broker confirms execution | UPDATE | `trades` | EXECUTED | trade_events: EXECUTED |
| Broker rejects/errors | UPDATE | `trades` | ERROR | trade_events: ERROR |
| BUY executed | INSERT/UPDATE | `positions` | OPEN | (via trade_events) |
| SELL partially closes position | UPDATE | `positions` | OPEN | (via trade_events) |
| Position fully closed | UPDATE | `positions` | CLOSED | trade_events: CLOSED |
| Profit target hit | UPDATE | `trades`, `positions` | CLOSED | trade_events: CLOSED |
| Stop loss triggered | UPDATE | `trades`, `positions` | CLOSED | trade_events: CLOSED |

### 9.3 Daily Metrics Aggregation Job

A background task in the position-monitor (or a separate cron job) aggregates daily metrics at market close.

```python
async def aggregate_daily_metrics():
    """Run at 16:30 ET daily (after market close)."""
    today = date.today()

    async with AsyncSessionLocal() as session:
        trades_today = await session.execute(
            select(Trade).where(func.date(Trade.created_at) == today)
        )
        all_trades = trades_today.scalars().all()

        closed_today = await session.execute(
            select(Position).where(
                Position.status == "CLOSED",
                func.date(Position.closed_at) == today,
            )
        )
        closed_positions = closed_today.scalars().all()

        open_count = await session.execute(
            select(func.count(Position.id)).where(Position.status == "OPEN")
        )

        metrics = DailyMetrics(
            date=today,
            total_trades=len(all_trades),
            executed_trades=sum(1 for t in all_trades if t.status == "EXECUTED"),
            rejected_trades=sum(1 for t in all_trades if t.status == "REJECTED"),
            errored_trades=sum(1 for t in all_trades if t.status == "ERROR"),
            closed_positions=len(closed_positions),
            total_pnl=sum(float(p.realized_pnl or 0) for p in closed_positions),
            winning_trades=sum(1 for p in closed_positions if (p.realized_pnl or 0) > 0),
            losing_trades=sum(1 for p in closed_positions if (p.realized_pnl or 0) < 0),
            open_positions_eod=open_count.scalar(),
        )

        session.add(metrics)
        await session.commit()
```

---

## 10. Phase 9: Monitoring, Metrics, and Suggestions

### 10.1 Prometheus Metrics Instrumentation

Each service exposes `/metrics` using `prometheus_client`.

```python
# shared/metrics.py

from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import Response

trades_total = Counter(
    "phoenixtrader_trades_total", "Total trades", ["status", "action", "ticker", "source"]
)
trade_latency = Histogram(
    "phoenixtrader_trade_latency_seconds", "Trade latency", ["stage"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
positions_open = Gauge("phoenixtrader_positions_open", "Open positions", ["ticker"])
pnl_realized = Counter("phoenixtrader_pnl_realized_total", "Realized PnL", ["close_reason"])
pnl_unrealized = Gauge("phoenixtrader_pnl_unrealized", "Unrealized PnL", ["ticker"])
buffer_slippage = Histogram(
    "phoenixtrader_buffer_slippage_pct", "Buffer vs fill slippage", ["ticker"],
    buckets=[0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30],
)
kafka_lag = Gauge("phoenixtrader_kafka_consumer_lag", "Consumer lag", ["topic", "group"])
broker_latency = Histogram(
    "phoenixtrader_broker_api_latency_seconds", "Broker API latency", ["operation"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
broker_errors = Counter("phoenixtrader_broker_api_errors_total", "Broker errors", ["operation", "error_type"])
daily_loss = Gauge("phoenixtrader_daily_loss", "Current daily loss")
buying_power = Gauge("phoenixtrader_buying_power", "Available buying power")
risk_utilization = Gauge("phoenixtrader_risk_utilization", "Risk limit utilization", ["metric"])


async def metrics_endpoint():
    return Response(content=generate_latest(), media_type="text/plain")
```

### 10.2 Health Check Endpoint

Every service implements:

```python
# shared/health.py

from fastapi import APIRouter

health_router = APIRouter()


@health_router.get("/healthz")
async def liveness():
    return {"status": "alive"}


@health_router.get("/readyz")
async def readiness():
    checks = {}
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = str(e)

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "not_ready", "checks": checks}
```

### 10.3 Grafana Dashboard Definitions

Provision these Grafana dashboards alongside the application:

| Dashboard | Panels | Data Source |
|-----------|--------|------------|
| **Trade Pipeline** | Messages/sec, parse rate, approval rate, execution rate, error rate, consumer lag per topic | Prometheus |
| **P&L Overview** | Cumulative P&L, daily P&L bars, win rate gauge, open position count, drawdown | PostgreSQL (via API) |
| **Broker Health** | API latency p50/p95/p99, error rate, order fill rate, buying power | Prometheus |
| **Infrastructure** | CPU/memory per pod, Kafka partition status, DB connections, Redis memory | Prometheus + cAdvisor |

---

## 11. Phase 10: Docker and Docker Compose

### 11.1 Base Dockerfile

```dockerfile
# Dockerfile.base
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY shared/ /app/shared/
COPY shared/config/defaults.yaml /app/shared/config/defaults.yaml
```

### 11.2 Service Dockerfile Template

```dockerfile
# services/<service-name>/Dockerfile
FROM python:3.13-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY shared/ /app/shared/

COPY services/<service-name>/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/<service-name>/ .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["python", "main.py"]
```

### 11.3 Dashboard Dockerfile

```dockerfile
# services/dashboard-ui/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY services/dashboard-ui/package*.json ./
RUN npm ci
COPY services/dashboard-ui/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY services/dashboard-ui/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
```

### 11.4 Full Docker Compose

```yaml
# docker-compose.yml
version: "3.9"

services:
  # --- Infrastructure ---
  kafka:
    image: apache/kafka-native:3.8
    ports: ["9092:9092"]
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_LOG_DIRS: /tmp/kraft-combined-logs
    healthcheck:
      test: ["/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "localhost:9092", "--list"]
      interval: 10s
      retries: 5

  schema-registry:
    image: confluentinc/cp-schema-registry:7.6.0
    depends_on: { kafka: { condition: service_healthy } }
    ports: ["8081:8081"]
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: kafka:9092

  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    environment: { POSTGRES_DB: phoenixtrader, POSTGRES_USER: phoenixtrader, POSTGRES_PASSWORD: localdev }
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U phoenixtrader"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  # --- Application Services ---
  discord-ingestor:
    build: { context: ., dockerfile: services/discord-ingestor/Dockerfile }
    depends_on: { kafka: { condition: service_healthy } }
    env_file: .env
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092

  trade-parser:
    build: { context: ., dockerfile: services/trade-parser/Dockerfile }
    depends_on: { kafka: { condition: service_healthy }, postgres: { condition: service_healthy } }
    env_file: .env
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      DATABASE_URL: postgresql+asyncpg://phoenixtrader:localdev@postgres:5432/phoenixtrader

  trade-gateway:
    build: { context: ., dockerfile: services/trade-gateway/Dockerfile }
    depends_on: { kafka: { condition: service_healthy }, postgres: { condition: service_healthy } }
    env_file: .env
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      DATABASE_URL: postgresql+asyncpg://phoenixtrader:localdev@postgres:5432/phoenixtrader

  trade-executor:
    build: { context: ., dockerfile: services/trade-executor/Dockerfile }
    depends_on: { kafka: { condition: service_healthy }, postgres: { condition: service_healthy }, redis: { condition: service_started } }
    env_file: .env
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      DATABASE_URL: postgresql+asyncpg://phoenixtrader:localdev@postgres:5432/phoenixtrader
      REDIS_URL: redis://redis:6379

  position-monitor:
    build: { context: ., dockerfile: services/position-monitor/Dockerfile }
    depends_on: { kafka: { condition: service_healthy }, postgres: { condition: service_healthy } }
    env_file: .env
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      DATABASE_URL: postgresql+asyncpg://phoenixtrader:localdev@postgres:5432/phoenixtrader

  notification-service:
    build: { context: ., dockerfile: services/notification-service/Dockerfile }
    depends_on: { kafka: { condition: service_healthy }, postgres: { condition: service_healthy } }
    env_file: .env
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      DATABASE_URL: postgresql+asyncpg://phoenixtrader:localdev@postgres:5432/phoenixtrader

  api-gateway:
    build: { context: ., dockerfile: services/api-gateway/Dockerfile }
    depends_on: { postgres: { condition: service_healthy }, redis: { condition: service_started } }
    ports: ["8000:8000"]
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://phoenixtrader:localdev@postgres:5432/phoenixtrader
      REDIS_URL: redis://redis:6379

  dashboard-ui:
    build: { context: ., dockerfile: services/dashboard-ui/Dockerfile }
    ports: ["3000:3000"]
    depends_on: [api-gateway]

volumes:
  pgdata:
```

---

## 12. Phase 11: Kubernetes Deployment

### 12.1 Namespace and Strimzi

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: copy-trader
```

```yaml
# k8s/kafka/kafka-cluster.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: copy-trader-kafka
  namespace: copy-trader
spec:
  kafka:
    version: 3.8.0
    replicas: 3
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false
    config:
      offsets.topic.replication.factor: 3
      transaction.state.log.replication.factor: 3
      transaction.state.log.min.isr: 2
    storage:
      type: persistent-claim
      size: 10Gi
  zookeeper:
    replicas: 0
  entityOperator:
    topicOperator: {}
```

### 12.2 Service Deployment Template

```yaml
# k8s/services/trade-executor.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trade-executor
  namespace: copy-trader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: trade-executor
  template:
    metadata:
      labels:
        app: trade-executor
    spec:
      containers:
        - name: trade-executor
          image: ghcr.io/your-org/trade-executor:latest
          resources:
            requests: { cpu: 200m, memory: 256Mi }
            limits: { cpu: 500m, memory: 512Mi }
          envFrom:
            - secretRef:
                name: broker-secrets
            - configMapRef:
                name: trading-config
          livenessProbe:
            httpGet: { path: /healthz, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet: { path: /readyz, port: 8000 }
            initialDelaySeconds: 5
            periodSeconds: 10
```

---

## 13. Phase 12: Agentic Extensions

### 13.1 Agent Plugin Registration

```python
# shared/agents/registry.py

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

_registry: dict[str, "AgentPlugin"] = {}


class AgentPlugin(Protocol):
    name: str
    version: str

    async def initialize(self, config: dict) -> None: ...
    async def process(self, event: dict) -> dict: ...
    async def health_check(self) -> bool: ...


def register_agent(agent: AgentPlugin):
    _registry[agent.name] = agent
    logger.info("Registered agent: %s v%s", agent.name, agent.version)


def get_agent(name: str) -> AgentPlugin | None:
    return _registry.get(name)


def list_agents() -> list[dict]:
    return [{"name": a.name, "version": a.version} for a in _registry.values()]
```

### 13.2 Signal Scoring Agent Example

```python
# services/agents/signal-scorer/main.py

import asyncio
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper


class SignalScoringAgent:
    name = "signal-scorer"
    version = "0.1.0"

    async def initialize(self, config: dict) -> None:
        pass  # Load ML model

    async def process(self, parsed_trade: dict) -> dict:
        """Score a parsed trade signal. Higher = more confident."""
        score = 0.5  # Placeholder: replace with ML model inference

        # Heuristic: known high-win-rate tickers get a boost
        if parsed_trade.get("ticker") in ("SPX", "QQQ", "IWM"):
            score += 0.1

        return {**parsed_trade, "agent_score": min(score, 1.0)}

    async def health_check(self) -> bool:
        return True


async def main():
    agent = SignalScoringAgent()
    await agent.initialize({})
    consumer = KafkaConsumerWrapper("parsed-trades", "signal-scorer-group")
    producer = KafkaProducerWrapper()
    await consumer.start()
    await producer.start()

    async def handle(msg):
        result = await agent.process(msg)
        await producer.send("agent-scores", key=msg["ticker"], value=result)

    await consumer.consume(handle)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 14. Testing Strategy

### 14.1 Test Layers

| Layer | Tool | Scope | Run When |
|-------|------|-------|----------|
| Unit | pytest | Individual functions (parser, buffer pricing, validator) | Every commit |
| Integration | pytest + testcontainers | Service + Kafka + PostgreSQL | Every PR |
| E2E | pytest + Docker Compose | Full pipeline: message -> parse -> execute | Pre-deploy |
| Load | locust | API Gateway under concurrent load | Weekly |

### 14.2 Unit Test Examples

```python
# tests/unit/test_buffer_pricing.py

from services.trade_executor.src.buffer_pricing import calculate_buffered_price


def test_buy_buffer_default():
    price, pct = calculate_buffered_price("BUY", 4.80, "SPX")
    assert price == 5.52  # 4.80 * 1.15
    assert pct == 0.15


def test_sell_buffer_default():
    price, pct = calculate_buffered_price("SELL", 6.50, "SPX")
    assert price == 5.53  # 6.50 * 0.85 = 5.525, rounded
    assert pct == 0.15


def test_min_price_floor():
    price, _ = calculate_buffered_price("SELL", 0.01, "AAPL")
    assert price >= 0.01
```

```python
# tests/unit/test_parser.py

from services.trade_parser.src.parser import parse_trade_message


def test_parse_buy():
    result = parse_trade_message("Bought SPX 6940C at 4.80")
    assert len(result["actions"]) == 1
    action = result["actions"][0]
    assert action["action"] == "BUY"
    assert action["ticker"] == "SPX"
    assert action["strike"] == 6940.0
    assert action["option_type"] == "CALL"
    assert action["price"] == 4.80


def test_parse_percentage_sell():
    result = parse_trade_message("Sold 50% SPX 6950C at 6.50")
    action = result["actions"][0]
    assert action["action"] == "SELL"
    assert action["quantity"] == "50%"
    assert action["is_percentage"] is True


def test_non_trade_message():
    result = parse_trade_message("Market looks bullish today")
    assert len(result["actions"]) == 0
```

### 14.3 Integration Test Example

```python
# tests/integration/test_trade_pipeline.py

import pytest
import asyncio
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="module")
def kafka():
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()


@pytest.fixture(scope="module")
def postgres():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()


@pytest.mark.asyncio
async def test_full_trade_flow(kafka, postgres):
    """Test: raw message -> parse -> gateway -> executor."""
    # 1. Produce raw message to Kafka
    # 2. Assert trade-parser consumes and produces parsed-trade
    # 3. Assert trade-gateway creates trade in DB with status PENDING
    # 4. Assert trade-gateway auto-approves
    # 5. Assert trade-executor consumes and processes
    pass  # Implement with real Kafka/PG connections
```

---

## 15. Runbook

### 15.1 Local Development Quickstart

```bash
# 1. Clone and setup
git clone <repo>
cd phoenix-trade-bot
cp .env.example .env
# Edit .env with your Discord bot token and Alpaca API keys

# 2. Start infrastructure
docker compose -f docker-compose.dev.yml up -d
sleep 10  # Wait for Kafka to be ready

# 3. Create Kafka topics
bash scripts/create-topics.sh

# 4. Initialize database
python -c "import asyncio; from shared.models.database import init_db; asyncio.run(init_db())"

# 5. Start services (each in a separate terminal)
python services/discord-ingestor/main.py
python services/trade-parser/main.py
python services/trade-gateway/main.py
python services/trade-executor/main.py
python services/position-monitor/main.py
python services/notification-service/main.py
python services/api-gateway/main.py

# 6. Start dashboard
cd services/dashboard-ui && npm install && npm run dev

# 7. Open dashboard
open http://localhost:3000
```

### 15.2 Common Operations

| Operation | Command |
|-----------|---------|
| View Kafka topics | `docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list` |
| Consume topic (debug) | `docker exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic raw-messages --from-beginning` |
| Check consumer lag | `docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group trade-parser-group` |
| Connect to DB | `docker exec -it postgres psql -U phoenixtrader -d phoenixtrader` |
| List trades | `SELECT id, trade_id, ticker, action, status, created_at FROM trades ORDER BY created_at DESC LIMIT 20;` |
| List open positions | `SELECT * FROM positions WHERE status = 'OPEN';` |
| Emergency kill switch | `curl -X POST http://localhost:8000/api/v1/config/kill-switch?enable=false` |
| Re-enable trading | `curl -X POST http://localhost:8000/api/v1/config/kill-switch?enable=true` |
| Check service health | `curl http://localhost:8000/api/v1/health` |

### 15.3 Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No trades in dashboard | Discord ingestor not connected | Check `DISCORD_BOT_TOKEN`, verify channel IDs |
| Trades stuck in PENDING | Gateway in manual mode or not running | Check `APPROVAL_MODE`, verify gateway is consuming |
| Trades stuck in PROCESSING | Executor failing silently | Check executor logs, verify Alpaca credentials |
| All trades REJECTED | Kill switch enabled or validation too strict | Check `ENABLE_TRADING`, review `MAX_POSITION_SIZE` |
| Kafka consumer lag growing | Consumer processing slower than producer | Check service logs, consider scaling replicas |
| Position monitor not triggering exits | Quotes returning 0 or monitor not running | Check broker API connectivity, verify poll interval |
| Dashboard showing stale data | WebSocket disconnected or cache TTL too long | Refresh browser, check API Gateway logs |
