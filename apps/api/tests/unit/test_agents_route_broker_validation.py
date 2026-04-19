"""Unit tests for broker validation in POST /agents route."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_pipeline_agent_requires_broker_type():
    """Test that pipeline agents require broker_type."""
    from apps.api.src.routes.agents import AgentCreate, validate_broker_config

    payload = AgentCreate(
        name="Test Pipeline Agent",
        type="trading",
        engine_type="pipeline",
        # Missing broker_type
    )

    mock_session = AsyncMock()
    user_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await validate_broker_config(payload, mock_session, user_id)

    assert exc_info.value.status_code == 400
    assert "require broker_type" in exc_info.value.detail


@pytest.mark.asyncio
async def test_pipeline_agent_with_invalid_broker_account():
    """Test that invalid broker_account_id returns 400."""
    from apps.api.src.routes.agents import AgentCreate, validate_broker_config

    payload = AgentCreate(
        name="Test Pipeline Agent",
        type="trading",
        engine_type="pipeline",
        broker_type="robinhood",
        broker_account_id=str(uuid.uuid4()),  # Account doesn't exist
    )

    # Mock session returns no account
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    user_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await validate_broker_config(payload, mock_session, user_id)

    assert exc_info.value.status_code == 400
    assert "not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_pipeline_agent_broker_type_mismatch():
    """Test that broker_type must match account's broker."""
    from apps.api.src.routes.agents import AgentCreate, validate_broker_config
    from shared.db.models.trading_account import TradingAccount

    broker_account_id = uuid.uuid4()
    payload = AgentCreate(
        name="Test Pipeline Agent",
        type="trading",
        engine_type="pipeline",
        broker_type="robinhood",  # Requesting robinhood
        broker_account_id=str(broker_account_id),
    )

    # Mock account with different broker
    mock_account = TradingAccount(
        id=broker_account_id,
        user_id=uuid.uuid4(),
        name="My IBKR Account",
        broker="ibkr",  # Account is IBKR, not Robinhood
        account_type="paper",
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_account
    mock_session.execute.return_value = mock_result

    user_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await validate_broker_config(payload, mock_session, user_id)

    assert exc_info.value.status_code == 400
    assert "does not match" in exc_info.value.detail


@pytest.mark.asyncio
async def test_pipeline_agent_valid_broker_config():
    """Test that valid broker config passes validation."""
    from apps.api.src.routes.agents import AgentCreate, validate_broker_config
    from shared.db.models.trading_account import TradingAccount

    broker_account_id = uuid.uuid4()
    user_id = uuid.uuid4()

    payload = AgentCreate(
        name="Test Pipeline Agent",
        type="trading",
        engine_type="pipeline",
        broker_type="robinhood",
        broker_account_id=str(broker_account_id),
    )

    # Mock valid account
    mock_account = TradingAccount(
        id=broker_account_id,
        user_id=user_id,
        name="My Robinhood Account",
        broker="robinhood",
        account_type="paper",
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_account
    mock_session.execute.return_value = mock_result

    # Should not raise
    await validate_broker_config(payload, mock_session, user_id)


@pytest.mark.asyncio
async def test_sdk_agent_skips_broker_validation():
    """Test that SDK agents skip broker validation."""
    from apps.api.src.routes.agents import AgentCreate, validate_broker_config

    payload = AgentCreate(
        name="Test SDK Agent",
        type="trading",
        engine_type="sdk",  # SDK engine
        # No broker_type
    )

    mock_session = AsyncMock()
    user_id = uuid.uuid4()

    # Should not raise (SDK agents don't need broker config)
    await validate_broker_config(payload, mock_session, user_id)
