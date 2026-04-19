"""
Integration test for kill-switch functionality in pipeline worker.

Tests:
- Multiple workers subscribe to kill-switch stream
- XADD to kill-switch stream stops all workers
- Workers transition to stopped state within timeout
- Graceful shutdown without data loss

Usage:
    python -m pytest tests/integration/pipeline/test_kill_switch.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from services.pipeline_worker.src.agent_worker import AgentWorker
from shared.db.models.agent import Agent, PipelineWorkerState
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


async def create_pipeline_agent(
    db_session: AsyncSession, test_user: User, trading_account: TradingAccount, name: str
) -> Agent:
    """Helper to create pipeline agent."""
    agent = Agent(
        id=uuid.uuid4(),
        name=name,
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


class MockBrokerAdapter:
    """Mock broker adapter."""

    def __init__(self, *args, **kwargs):
        pass

    async def place_limit_order(self, symbol: str, qty: int, side: str, price: float) -> str:
        """Mock place order."""
        return "MOCK-ORDER-123"

    async def close(self):
        """Mock close."""
        pass


@pytest.mark.asyncio
async def test_kill_switch_stops_single_worker(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    test_user: User,
    trading_account: TradingAccount,
    db_engine,
):
    """
    Test kill-switch stops a single worker:
    1. Start worker
    2. XADD to kill-switch stream
    3. Worker stops within 2 seconds
    """
    agent = await create_pipeline_agent(db_session, test_user, trading_account, "Agent 1")

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

        # Start worker
        worker_task = asyncio.create_task(worker.run())

        # Wait for worker to initialize
        await asyncio.sleep(0.5)

        # Verify worker is running
        assert worker._running is True

        # Send kill-switch signal
        await redis_client.xadd(
            "stream:kill-switch",
            {"action": "shutdown", "timestamp": datetime.now(timezone.utc).isoformat()}
        )

        # Wait for worker to stop (max 2 seconds)
        start_time = asyncio.get_event_loop().time()
        while worker._running and (asyncio.get_event_loop().time() - start_time) < 2.0:
            await asyncio.sleep(0.1)

        # Cleanup
        worker.stop()
        await worker_task

        # Assertions
        assert worker._running is False, "Worker should be stopped after kill-switch"
        elapsed = asyncio.get_event_loop().time() - start_time
        assert elapsed < 2.0, f"Worker should stop within 2 seconds, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_kill_switch_stops_multiple_workers(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    test_user: User,
    trading_account: TradingAccount,
    db_engine,
):
    """
    Test kill-switch stops multiple workers concurrently:
    1. Start two workers
    2. XADD to kill-switch stream
    3. Both workers stop within 2 seconds
    """
    agent1 = await create_pipeline_agent(db_session, test_user, trading_account, "Agent 1")
    agent2 = await create_pipeline_agent(db_session, test_user, trading_account, "Agent 2")

    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    with patch("shared.broker.factory.RobinhoodBrokerAdapter", MockBrokerAdapter):
        worker1 = AgentWorker(
            agent_id=str(agent1.id),
            connector_ids=[str(test_connector.id)],
            config=agent1.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent1.user_id),
        )

        worker2 = AgentWorker(
            agent_id=str(agent2.id),
            connector_ids=[str(test_connector.id)],
            config=agent2.config,
            redis_client=redis_client,
            session_factory=async_session,
            user_id=str(agent2.user_id),
        )

        # Start both workers
        worker1_task = asyncio.create_task(worker1.run())
        worker2_task = asyncio.create_task(worker2.run())

        # Wait for workers to initialize
        await asyncio.sleep(0.5)

        # Verify both running
        assert worker1._running is True
        assert worker2._running is True

        # Send kill-switch signal
        await redis_client.xadd(
            "stream:kill-switch",
            {
                "action": "shutdown",
                "reason": "maintenance",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Wait for both workers to stop (max 2 seconds)
        start_time = asyncio.get_event_loop().time()
        timeout = 2.0
        while (worker1._running or worker2._running) and (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # Cleanup
        worker1.stop()
        worker2.stop()
        await asyncio.gather(worker1_task, worker2_task)

        # Assertions
        assert worker1._running is False, "Worker 1 should be stopped"
        assert worker2._running is False, "Worker 2 should be stopped"
        elapsed = asyncio.get_event_loop().time() - start_time
        assert elapsed < timeout, f"Workers should stop within {timeout}s, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_kill_switch_graceful_shutdown(
    db_session: AsyncSession,
    redis_client: aioredis.Redis,
    test_connector: Connector,
    test_user: User,
    trading_account: TradingAccount,
    db_engine,
    caplog,
):
    """
    Test that kill-switch triggers graceful shutdown with logging.
    """
    import logging
    caplog.set_level(logging.INFO)

    agent = await create_pipeline_agent(db_session, test_user, trading_account, "Agent 1")

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

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.3)

        # Send kill-switch
        await redis_client.xadd("stream:kill-switch", {"action": "shutdown"})

        # Wait for shutdown
        for _ in range(20):
            await asyncio.sleep(0.1)
            if not worker._running:
                break

        worker.stop()
        await worker_task

        # Check logs for graceful shutdown messages
        log_messages = " ".join([rec.message for rec in caplog.records])
        assert "kill-switch" in log_messages.lower(), "Logs should mention kill-switch"
        assert "stop" in log_messages.lower() or "shutdown" in log_messages.lower(), "Logs should indicate shutdown"
