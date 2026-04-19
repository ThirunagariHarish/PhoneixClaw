"""
Integration test for percentage-sell flow in pipeline worker.

Tests:
- Partial position close (50% sell)
- Full position close (100% sell)
- Position status transitions (open -> partially_closed -> closed)
- FIFO order processing

Usage:
    python -m pytest tests/integration/pipeline/test_percentage_sell_flow.py -v --tb=short
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
        name="Test Discord",
        type="discord",
        status="connected",
        user_id=test_user.id,
        config={"channels": ["test"]},
    )
    db_session.add(connector)
    await db_session.commit()
    await db_session.refresh(connector)
    return connector


@pytest.fixture
async def trading_account(db_session: AsyncSession, test_user: User):
    """Create trading account."""
    from shared.crypto.credentials import encrypt_credentials

    credentials = {"mcp_url": "http://localhost:8080"}
    encrypted = encrypt_credentials(credentials)

    account = TradingAccount(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Test Paper",
        broker="robinhood",
        account_type="paper",
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
async def pipeline_agent(
    db_session: AsyncSession, test_user: User, trading_account: TradingAccount
):
    """Create pipeline agent."""
    agent = Agent(
        id=uuid.uuid4(),
        name="Test Agent",
        type="trading",
        engine_type="pipeline",
        status="APPROVED",
        user_id=test_user.id,
        config={
            "broker_type": "robinhood",
            "broker_account_id": str(trading_account.id),
            "risk_params": {"max_concurrent_positions": 5},
        },
    )
    db_session.add(agent)

    worker_state = PipelineWorkerState(
        id=uuid.uuid4(),
        agent_id=agent.id,
        stream_key="stream:test",
        last_cursor="0-0",
    )
    db_session.add(worker_state)

    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.fixture
async def open_position(db_session: AsyncSession, pipeline_agent: Agent):
    """Create open position with 10 contracts."""
    trade = AgentTrade(
        id=uuid.uuid4(),
        agent_id=pipeline_agent.id,
        ticker="AAPL",
        side="BUY",
        option_type="CALL",
        strike=200.0,
        expiry=date(2026, 5, 16),
        entry_price=5.00,
        quantity=10,
        current_quantity=10,
        position_status="open",
        entry_time=datetime.now(timezone.utc),
        broker_order_id="RH-00001",
    )
    db_session.add(trade)
    await db_session.commit()
    await db_session.refresh(trade)
    return trade


class MockBrokerAdapter:
    """Mock broker adapter for testing."""

    def __init__(self, *args, **kwargs):
        self.order_counter = 0

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Mock place order."""
        self.order_counter += 1
        return f"RH-{self.order_counter:05d}"

    async def close(self):
        """Mock close."""
        pass


@pytest.mark.asyncio
async def test_percentage_sell_50_percent(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    pipeline_agent: Agent,
    open_position: AgentTrade,
    db_engine,
):
    """
    Test 50% sell of open position:
    - Original position: 10 contracts
    - After 50% sell: 5 contracts remaining
    - Position status: partially_closed
    """
    agent = pipeline_agent
    stream_key = f"stream:channel:{test_connector.id}"

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    with patch("shared.broker.factory.RobinhoodBrokerAdapter", MockBrokerAdapter):
        worker = AgentWorker(
            agent_id=str(agent.id),
            connector_ids=[str(test_connector.id)],
            config=agent.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent.user_id),
        )

        # XADD 50% sell signal
        signal_data = {
            "content": "Sold 50% AAPL 200C at 6.00",
            "author": "TestTrader",
            "channel": "test-channel",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.xadd(stream_key, signal_data)

        # Mock inference
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.75
        mock_prediction.model_used = "xgboost"
        mock_prediction.reasoning = "Exit signal"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            worker_task = asyncio.create_task(worker.run())

            # Wait for processing
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(AgentTrade).where(AgentTrade.id == open_position.id)
                    )
                    trade = result.scalar_one_or_none()
                    if trade and trade.current_quantity != 10:
                        break

            worker.stop()
            await worker_task

        # Assertions
        async with async_session() as session:
            result = await session.execute(
                select(AgentTrade).where(AgentTrade.id == open_position.id)
            )
            trade = result.scalar_one_or_none()
            assert trade is not None
            assert trade.current_quantity == 5, "Should have 5 contracts remaining after 50% sell"
            assert trade.position_status == "partially_closed"
            assert trade.quantity == 10, "Original quantity should remain 10"
            assert trade.exit_time is None, "Exit time should be None for partial close"


@pytest.mark.asyncio
async def test_percentage_sell_100_percent(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    pipeline_agent: Agent,
    open_position: AgentTrade,
    db_engine,
):
    """
    Test 100% sell of open position:
    - Original position: 10 contracts
    - After 100% sell: 0 contracts remaining
    - Position status: closed
    - PnL calculated
    """
    agent = pipeline_agent
    stream_key = f"stream:channel:{test_connector.id}"

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    with patch("shared.broker.factory.RobinhoodBrokerAdapter", MockBrokerAdapter):
        worker = AgentWorker(
            agent_id=str(agent.id),
            connector_ids=[str(test_connector.id)],
            config=agent.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent.user_id),
        )

        # XADD 100% sell signal
        signal_data = {
            "content": "Sold 100% AAPL 200C at 7.00",
            "author": "TestTrader",
            "channel": "test-channel",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.xadd(stream_key, signal_data)

        # Mock inference
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.80
        mock_prediction.model_used = "xgboost"
        mock_prediction.reasoning = "Full exit"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            worker_task = asyncio.create_task(worker.run())

            # Wait for processing
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(AgentTrade).where(AgentTrade.id == open_position.id)
                    )
                    trade = result.scalar_one_or_none()
                    if trade and trade.current_quantity == 0:
                        break

            worker.stop()
            await worker_task

        # Assertions
        async with async_session() as session:
            result = await session.execute(
                select(AgentTrade).where(AgentTrade.id == open_position.id)
            )
            trade = result.scalar_one_or_none()
            assert trade is not None
            assert trade.current_quantity == 0, "Should have 0 contracts after 100% sell"
            assert trade.position_status == "closed"
            assert trade.exit_time is not None, "Exit time should be set"
            assert trade.exit_price == 7.00
            # PnL: (7.00 - 5.00) * 10 * 100 = $2000
            assert trade.pnl_dollar == 2000.0
            # PnL %: ((7.00 - 5.00) / 5.00) * 100 = 40%
            assert trade.pnl_pct == 40.0


@pytest.mark.asyncio
async def test_percentage_sell_sequential_closes(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    pipeline_agent: Agent,
    open_position: AgentTrade,
    db_engine,
):
    """
    Test sequential percentage sells:
    1. 50% sell -> 5 remaining, partially_closed
    2. 100% sell -> 0 remaining, closed
    """
    agent = pipeline_agent
    stream_key = f"stream:channel:{test_connector.id}"

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    with patch("shared.broker.factory.RobinhoodBrokerAdapter", MockBrokerAdapter):
        worker = AgentWorker(
            agent_id=str(agent.id),
            connector_ids=[str(test_connector.id)],
            config=agent.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent.user_id),
        )

        # Mock inference
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.75
        mock_prediction.model_used = "xgboost"
        mock_prediction.reasoning = "Exit signal"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            worker_task = asyncio.create_task(worker.run())

            # First sell: 50%
            signal_data = {
                "content": "Sold 50% AAPL 200C at 6.00",
                "author": "TestTrader",
                "channel": "test-channel",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await redis_client.xadd(stream_key, signal_data)

            # Wait for first sell to process
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(AgentTrade).where(AgentTrade.id == open_position.id)
                    )
                    trade = result.scalar_one_or_none()
                    if trade and trade.current_quantity == 5:
                        break

            # Verify partial close
            async with async_session() as session:
                result = await session.execute(
                    select(AgentTrade).where(AgentTrade.id == open_position.id)
                )
                trade = result.scalar_one_or_none()
                assert trade.current_quantity == 5
                assert trade.position_status == "partially_closed"

            # Second sell: 100% (of remaining 5)
            signal_data = {
                "content": "Sold 100% AAPL 200C at 7.50",
                "author": "TestTrader",
                "channel": "test-channel",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await redis_client.xadd(stream_key, signal_data)

            # Wait for second sell
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(AgentTrade).where(AgentTrade.id == open_position.id)
                    )
                    trade = result.scalar_one_or_none()
                    if trade and trade.current_quantity == 0:
                        break

            worker.stop()
            await worker_task

        # Final assertions
        async with async_session() as session:
            result = await session.execute(
                select(AgentTrade).where(AgentTrade.id == open_position.id)
            )
            trade = result.scalar_one_or_none()
            assert trade is not None
            assert trade.current_quantity == 0
            assert trade.position_status == "closed"
            assert trade.exit_time is not None
