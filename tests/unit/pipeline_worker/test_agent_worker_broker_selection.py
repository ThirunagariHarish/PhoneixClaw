"""Unit tests for broker selection in pipeline worker."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_broker_selection_robinhood():
    """Test broker adapter initialization with Robinhood."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    config = {
        "broker_type": "robinhood",
        "broker_account_id": str(uuid.uuid4()),
    }

    # Mock TradingAccount
    mock_account = MagicMock()
    mock_account.broker = "robinhood"
    mock_account.account_type = "paper"
    mock_account.credentials_encrypted = b"encrypted_creds"

    # Mock session factory
    async def mock_session_factory():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_account
        mock_session.execute.return_value = mock_result
        yield mock_session

    mock_redis = AsyncMock()

    # Mock broker factory
    with patch("services.pipeline_worker.src.agent_worker.create_broker_adapter") as mock_factory:
        mock_adapter = MagicMock()
        mock_factory.return_value = mock_adapter

        worker = AgentWorker(
            agent_id=agent_id,
            connector_ids=[],
            config=config,
            redis_client=mock_redis,
            session_factory=mock_session_factory,
            user_id=user_id,
        )

        await worker._init_broker_adapter()

        # Verify broker adapter was created with correct params
        mock_factory.assert_called_once_with(
            "robinhood",
            b"encrypted_creds",
            paper_mode=True,
        )
        assert worker._broker_adapter is mock_adapter


@pytest.mark.asyncio
async def test_broker_selection_ibkr():
    """Test broker adapter initialization with IBKR."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    config = {
        "broker_type": "ibkr",
        "broker_account_id": str(uuid.uuid4()),
    }

    # Mock TradingAccount
    mock_account = MagicMock()
    mock_account.broker = "ibkr"
    mock_account.account_type = "live"
    mock_account.credentials_encrypted = b"ibkr_creds"

    async def mock_session_factory():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_account
        mock_session.execute.return_value = mock_result
        yield mock_session

    mock_redis = AsyncMock()

    with patch("services.pipeline_worker.src.agent_worker.create_broker_adapter") as mock_factory:
        mock_adapter = MagicMock()
        mock_factory.return_value = mock_adapter

        worker = AgentWorker(
            agent_id=agent_id,
            connector_ids=[],
            config=config,
            redis_client=mock_redis,
            session_factory=mock_session_factory,
            user_id=user_id,
        )

        await worker._init_broker_adapter()

        mock_factory.assert_called_once_with(
            "ibkr",
            b"ibkr_creds",
            paper_mode=False,
        )
        assert worker._broker_adapter is mock_adapter


@pytest.mark.asyncio
async def test_broker_selection_fallback_to_default():
    """Test broker adapter falls back to user's default account when broker_account_id is missing."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    config = {
        "broker_type": "robinhood",
        # No broker_account_id
    }

    mock_account = MagicMock()
    mock_account.broker = "robinhood"
    mock_account.account_type = "paper"
    mock_account.credentials_encrypted = b"default_creds"

    async def mock_session_factory():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_account
        mock_session.execute.return_value = mock_result
        yield mock_session

    mock_redis = AsyncMock()

    with patch("services.pipeline_worker.src.agent_worker.create_broker_adapter") as mock_factory:
        mock_adapter = MagicMock()
        mock_factory.return_value = mock_adapter

        worker = AgentWorker(
            agent_id=agent_id,
            connector_ids=[],
            config=config,
            redis_client=mock_redis,
            session_factory=mock_session_factory,
            user_id=user_id,
        )

        await worker._init_broker_adapter()

        assert worker._broker_adapter is mock_adapter


@pytest.mark.asyncio
async def test_broker_selection_no_account_found():
    """Test broker adapter handles missing account gracefully."""
    from services.pipeline_worker.src.agent_worker import AgentWorker

    agent_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    config = {
        "broker_type": "robinhood",
        "broker_account_id": str(uuid.uuid4()),
    }

    async def mock_session_factory():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No account found
        mock_session.execute.return_value = mock_result
        yield mock_session

    mock_redis = AsyncMock()

    worker = AgentWorker(
        agent_id=agent_id,
        connector_ids=[],
        config=config,
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        user_id=user_id,
    )

    await worker._init_broker_adapter()

    # Should not crash, broker_adapter remains None
    assert worker._broker_adapter is None
