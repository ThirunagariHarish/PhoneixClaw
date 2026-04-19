"""
Integration test for dry-run mode in pipeline worker.

Tests:
- Dry-run mode prevents actual broker calls
- Signals are processed but trades are not executed
- Logs contain "DRY-RUN" messages
- No agent_trades records created
- pipeline_worker_state increments signals_processed but not trades_executed

Usage:
    python -m pytest tests/integration/pipeline/test_dry_run_mode.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
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
async def dry_run_agent(
    db_session: AsyncSession, test_user: User, trading_account: TradingAccount
):
    """Create pipeline agent with dry_run_mode enabled."""
    agent = Agent(
        id=uuid.uuid4(),
        name="Dry Run Test Agent",
        type="trading",
        engine_type="pipeline",
        status="APPROVED",
        user_id=test_user.id,
        config={
            "broker_type": "robinhood",
            "broker_account_id": str(trading_account.id),
            "dry_run_mode": True,  # Enable dry-run
            "risk_params": {"max_concurrent_positions": 5},
        },
    )
    db_session.add(agent)

    worker_state = PipelineWorkerState(
        id=uuid.uuid4(),
        agent_id=agent.id,
        stream_key="stream:test",
        last_cursor="0-0",
        signals_processed=0,
        trades_executed=0,
        signals_skipped=0,
    )
    db_session.add(worker_state)

    await db_session.commit()
    await db_session.refresh(agent)
    return agent


class MockBrokerAdapter:
    """Mock broker adapter that should NOT be called in dry-run mode."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """This should NOT be called in dry-run mode."""
        self.calls.append(("place_limit_order", symbol, qty, side, price))
        raise AssertionError("Broker adapter should not be called in dry-run mode")

    async def close(self):
        """Mock close."""
        pass


@pytest.mark.asyncio
async def test_dry_run_mode_prevents_broker_calls(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    dry_run_agent: Agent,
    db_engine,
    caplog,
):
    """
    Test that dry-run mode prevents actual broker calls:
    1. Signal is processed
    2. Broker adapter is NOT called
    3. No agent_trades record created
    4. signals_processed incremented
    5. trades_executed NOT incremented
    6. Logs contain "DRY-RUN"
    """
    import logging
    caplog.set_level(logging.INFO)

    agent = dry_run_agent
    stream_key = f"stream:channel:{test_connector.id}"

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    mock_adapter = MockBrokerAdapter()

    with patch("shared.broker.factory.RobinhoodBrokerAdapter", return_value=mock_adapter):
        worker = AgentWorker(
            agent_id=str(agent.id),
            connector_ids=[str(test_connector.id)],
            config=agent.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent.user_id),
        )

        # XADD buy signal
        signal_data = {
            "content": "Bought AAPL 200C at 5.00 Exp: 05/16/2026",
            "author": "TestTrader",
            "channel": "test-channel",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.xadd(stream_key, signal_data)

        # Mock inference to return TRADE
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.75
        mock_prediction.model_used = "xgboost"
        mock_prediction.reasoning = "Strong signal"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            worker_task = asyncio.create_task(worker.run())

            # Wait for signal to be processed
            initial_processed = 0
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(PipelineWorkerState).where(PipelineWorkerState.agent_id == agent.id)
                    )
                    state = result.scalar_one_or_none()
                    if state and state.signals_processed > initial_processed:
                        break

            worker.stop()
            await worker_task

        # Assertions

        # 1. Broker adapter should NOT have been called
        assert len(mock_adapter.calls) == 0, "Broker adapter should not be called in dry-run mode"

        # 2. No agent_trades record should exist
        async with async_session() as session:
            result = await session.execute(
                select(AgentTrade).where(AgentTrade.agent_id == agent.id)
            )
            trades = result.scalars().all()
            assert len(trades) == 0, "No trades should be recorded in dry-run mode"

        # 3. Check pipeline worker state
        async with async_session() as session:
            result = await session.execute(
                select(PipelineWorkerState).where(PipelineWorkerState.agent_id == agent.id)
            )
            state = result.scalar_one_or_none()
            assert state is not None
            assert state.signals_processed >= 1, "Signal should be processed"
            assert state.trades_executed == 0, "No trades should be executed in dry-run mode"
            assert state.signals_skipped >= 1, "Signal should be skipped (dry-run)"

        # 4. Check logs contain "DRY-RUN"
        log_messages = [rec.message for rec in caplog.records]
        dry_run_logs = [msg for msg in log_messages if "DRY-RUN" in msg or "dry-run" in msg.lower()]
        assert len(dry_run_logs) > 0, "Logs should contain DRY-RUN messages"


@pytest.mark.asyncio
async def test_dry_run_mode_logs_intent(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    dry_run_agent: Agent,
    db_engine,
    caplog,
):
    """
    Test that dry-run mode logs the trade intent clearly.
    """
    import logging
    caplog.set_level(logging.INFO)

    agent = dry_run_agent
    stream_key = f"stream:channel:{test_connector.id}"

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    mock_adapter = MockBrokerAdapter()

    with patch("shared.broker.factory.RobinhoodBrokerAdapter", return_value=mock_adapter):
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

        # Mock inference
        mock_prediction = MagicMock()
        mock_prediction.prediction = "TRADE"
        mock_prediction.confidence = 0.80
        mock_prediction.model_used = "xgboost"
        mock_prediction.reasoning = "Test"

        with patch.object(worker._inference, "predict", return_value=mock_prediction):
            worker_task = asyncio.create_task(worker.run())

            # Wait for processing
            for _ in range(50):
                await asyncio.sleep(0.1)
                async with async_session() as session:
                    result = await session.execute(
                        select(PipelineWorkerState).where(PipelineWorkerState.agent_id == agent.id)
                    )
                    state = result.scalar_one_or_none()
                    if state and state.signals_processed > 0:
                        break

            worker.stop()
            await worker_task

        # Check logs contain trade details and DRY-RUN marker
        log_messages = " ".join([rec.message for rec in caplog.records])
        assert "DRY-RUN" in log_messages or "dry-run" in log_messages.lower()
        assert "SPY" in log_messages, "Log should mention ticker"
        assert "buy" in log_messages.lower() or "BUY" in log_messages, "Log should mention side"
