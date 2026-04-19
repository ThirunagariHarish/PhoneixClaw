"""
Integration test for pipeline worker broker flow.

Tests the end-to-end pipeline: Redis stream signal -> pipeline worker -> broker adapter -> DB trade record.

Uses mocked broker adapters (Robinhood and IBKR) in paper mode.
Requires Redis and PostgreSQL running.

Usage:
    python -m pytest tests/integration/pipeline/test_pipeline_flow_broker.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from services.pipeline_worker.src.agent_worker import AgentWorker
from shared.db.models.agent import Agent, PipelineWorkerState
from shared.db.models.agent_trade import AgentTrade
from shared.db.models.base import Base
from shared.db.models.connector import Connector
from shared.db.models.trading_account import TradingAccount
from shared.db.models.user import User


@pytest.fixture(scope="module")
async def db_engine():
    """In-memory SQLite engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Async session for each test."""
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.fixture
async def redis_client():
    """Redis client for testing."""
    try:
        client = aioredis.from_url("redis://localhost:6379/15", decode_responses=True)
        await client.ping()
        yield client
        # Cleanup: flush test DB
        await client.flushdb()
        await client.close()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create test user."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="dummy_hash",
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_connector(db_session: AsyncSession, test_user: User):
    """Create test connector."""
    connector = Connector(
        id=uuid.uuid4(),
        name="Test Discord Server",
        type="discord",
        status="connected",
        user_id=test_user.id,
        config={"server_id": "123456789", "channels": ["test-channel"]},
    )
    db_session.add(connector)
    await db_session.commit()
    await db_session.refresh(connector)
    return connector


@pytest.fixture
async def robinhood_trading_account(db_session: AsyncSession, test_user: User):
    """Create Robinhood paper trading account with encrypted credentials."""
    from shared.crypto.credentials import encrypt_credentials

    credentials = {"mcp_url": "http://robinhood-mcp-server:8080"}
    encrypted = encrypt_credentials(credentials)

    account = TradingAccount(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Robinhood Paper",
        broker="robinhood",
        account_type="paper",
        broker_account_id="RH12345",
        credentials_encrypted=encrypted.decode(),
        balance=10000.0,
        buying_power=10000.0,
        is_active=True,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest.fixture
async def ibkr_trading_account(db_session: AsyncSession, test_user: User):
    """Create IBKR paper trading account with encrypted credentials."""
    from shared.crypto.credentials import encrypt_credentials

    credentials = {
        "host": "ib-gateway",
        "port": 4001,
        "paper_account_id": "DU12345",
    }
    encrypted = encrypt_credentials(credentials)

    account = TradingAccount(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="IBKR Paper",
        broker="ibkr",
        account_type="paper",
        broker_account_id="DU12345",
        credentials_encrypted=encrypted.decode(),
        balance=25000.0,
        buying_power=25000.0,
        is_active=True,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest.fixture
async def pipeline_agent_robinhood(
    db_session: AsyncSession, test_user: User, robinhood_trading_account: TradingAccount
):
    """Create pipeline agent configured with Robinhood broker."""
    agent = Agent(
        id=uuid.uuid4(),
        name="Test Pipeline Agent - Robinhood",
        type="trading",
        engine_type="pipeline",
        status="APPROVED",
        user_id=test_user.id,
        config={
            "broker_type": "robinhood",
            "broker_account_id": str(robinhood_trading_account.id),
            "risk_params": {
                "max_concurrent_positions": 5,
                "max_position_size_pct": 10.0,
            },
        },
    )
    db_session.add(agent)

    # Create PipelineWorkerState
    worker_state = PipelineWorkerState(
        id=uuid.uuid4(),
        agent_id=agent.id,
        stream_key="stream:channel:test",
        last_cursor="0-0",
        signals_processed=0,
        trades_executed=0,
        signals_skipped=0,
    )
    db_session.add(worker_state)

    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.fixture
async def pipeline_agent_ibkr(
    db_session: AsyncSession, test_user: User, ibkr_trading_account: TradingAccount
):
    """Create pipeline agent configured with IBKR broker."""
    agent = Agent(
        id=uuid.uuid4(),
        name="Test Pipeline Agent - IBKR",
        type="trading",
        engine_type="pipeline",
        status="APPROVED",
        user_id=test_user.id,
        config={
            "broker_type": "ibkr",
            "broker_account_id": str(ibkr_trading_account.id),
            "risk_params": {
                "max_concurrent_positions": 3,
                "max_position_size_pct": 5.0,
            },
        },
    )
    db_session.add(agent)

    # Create PipelineWorkerState
    worker_state = PipelineWorkerState(
        id=uuid.uuid4(),
        agent_id=agent.id,
        stream_key="stream:channel:test",
        last_cursor="0-0",
        signals_processed=0,
        trades_executed=0,
        signals_skipped=0,
    )
    db_session.add(worker_state)

    await db_session.commit()
    await db_session.refresh(agent)
    return agent


class MockRobinhoodAdapter:
    """Mock Robinhood broker adapter."""

    def __init__(self, *args, **kwargs):
        self.orders = []

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Mock place order - returns synthetic order ID."""
        order_id = f"RH-{len(self.orders) + 1:05d}"
        self.orders.append({
            "order_id": order_id,
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "price": price,
        })
        return order_id

    async def close(self):
        """Mock close."""
        pass


class MockIBKRAdapter:
    """Mock IBKR broker adapter."""

    def __init__(self, *args, **kwargs):
        self.orders = []

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Mock place order - returns synthetic order ID."""
        order_id = f"IB-{len(self.orders) + 1:05d}"
        self.orders.append({
            "order_id": order_id,
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "price": price,
        })
        return order_id

    async def close(self):
        """Mock close."""
        pass


@pytest.mark.asyncio
async def test_pipeline_flow_robinhood(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    pipeline_agent_robinhood: Agent,
    db_engine,
):
    """
    Test pipeline flow with Robinhood broker:
    1. XADD signal to Redis stream
    2. Start AgentWorker
    3. Assert trade recorded in DB with broker_order_id
    4. Assert pipeline_worker_state updated
    """
    agent = pipeline_agent_robinhood
    stream_key = f"stream:channel:{test_connector.id}"

    # Create session factory
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # Mock broker adapter
    with patch("shared.broker.factory.RobinhoodBrokerAdapter", MockRobinhoodAdapter):
        # Create worker
        worker = AgentWorker(
            agent_id=str(agent.id),
            connector_ids=[str(test_connector.id)],
            config=agent.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent.user_id),
        )

        # XADD signal
        signal_data = {
            "content": "Bought AAPL 200C at 5.00 Exp: 05/16/2026",
            "author": "TestTrader",
            "channel": "test-channel",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.xadd(stream_key, signal_data)

        # Mock inference client to return TRADE decision
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.75
        mock_prediction.model_used = "xgboost"
        mock_prediction.reasoning = "Strong bullish signal"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            # Start worker in background
            worker_task = asyncio.create_task(worker.run())

            # Wait for processing (max 5s)
            for _ in range(50):
                await asyncio.sleep(0.1)
                # Check if trade was recorded
                async with async_session() as session:
                    result = await session.execute(
                        select(AgentTrade).where(AgentTrade.agent_id == agent.id)
                    )
                    trade = result.scalar_one_or_none()
                    if trade:
                        break

            # Stop worker
            worker.stop()
            await worker_task

        # Assertions
        async with async_session() as session:
            # Check trade record
            result = await session.execute(
                select(AgentTrade).where(AgentTrade.agent_id == agent.id)
            )
            trade = result.scalar_one_or_none()
            assert trade is not None, "Trade should be recorded"
            assert trade.ticker == "AAPL"
            assert trade.side == "BUY"
            assert trade.option_type == "CALL"
            assert trade.strike == 200.0
            assert trade.expiry == date(2026, 5, 16)
            assert trade.entry_price == 5.00
            assert trade.quantity == 1
            assert trade.current_quantity == 1
            assert trade.position_status == "open"
            assert trade.broker_order_id is not None
            assert trade.broker_order_id.startswith("RH-")

            # Check pipeline worker state updated
            result = await session.execute(
                select(PipelineWorkerState).where(PipelineWorkerState.agent_id == agent.id)
            )
            state = result.scalar_one_or_none()
            assert state is not None
            assert state.trades_executed >= 1
            assert state.signals_processed >= 1


@pytest.mark.asyncio
async def test_pipeline_flow_ibkr(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    pipeline_agent_ibkr: Agent,
    db_engine,
):
    """
    Test pipeline flow with IBKR broker:
    1. XADD signal to Redis stream
    2. Start AgentWorker
    3. Assert trade recorded in DB with broker_order_id starting with 'IB-'
    """
    agent = pipeline_agent_ibkr
    stream_key = f"stream:channel:{test_connector.id}"

    # Create session factory
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # Mock broker adapter
    with patch("shared.broker.factory.IBKRBrokerAdapter", MockIBKRAdapter):
        # Create worker
        worker = AgentWorker(
            agent_id=str(agent.id),
            connector_ids=[str(test_connector.id)],
            config=agent.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent.user_id),
        )

        # XADD signal
        signal_data = {
            "content": "Bought SPY 600C at 3.50 Exp: 06/20/2026",
            "author": "TestTrader",
            "channel": "test-channel",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.xadd(stream_key, signal_data)

        # Mock inference client
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.80
        mock_prediction.model_used = "lightgbm"
        mock_prediction.reasoning = "High confidence trade"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            # Start worker
            worker_task = asyncio.create_task(worker.run())

            # Wait for processing
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(AgentTrade).where(AgentTrade.agent_id == agent.id)
                    )
                    trade = result.scalar_one_or_none()
                    if trade:
                        break

            # Stop worker
            worker.stop()
            await worker_task

        # Assertions
        async with async_session() as session:
            result = await session.execute(
                select(AgentTrade).where(AgentTrade.agent_id == agent.id)
            )
            trade = result.scalar_one_or_none()
            assert trade is not None, "Trade should be recorded"
            assert trade.ticker == "SPY"
            assert trade.side == "BUY"
            assert trade.option_type == "CALL"
            assert trade.strike == 600.0
            assert trade.expiry == date(2026, 6, 20)
            assert trade.entry_price == 3.50
            assert trade.current_quantity == 1
            assert trade.position_status == "open"
            assert trade.broker_order_id is not None
            assert trade.broker_order_id.startswith("IB-")

            # Check state
            result = await session.execute(
                select(PipelineWorkerState).where(PipelineWorkerState.agent_id == agent.id)
            )
            state = result.scalar_one_or_none()
            assert state is not None
            assert state.trades_executed >= 1
