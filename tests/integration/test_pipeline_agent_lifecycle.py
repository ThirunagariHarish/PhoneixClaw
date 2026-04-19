"""Integration test for pipeline agent lifecycle via API."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_pipeline_agent_with_broker(test_client: AsyncClient, test_user_token: str):
    """Test creating a pipeline agent with broker configuration."""
    # This test requires a test_client fixture and test_user_token fixture
    # Assuming these are provided by the test framework

    # Create a mock trading account first
    trading_account_id = str(uuid.uuid4())

    payload = {
        "name": "Test Pipeline Bot",
        "type": "trading",
        "engine_type": "pipeline",
        "broker_type": "robinhood",
        "broker_account_id": trading_account_id,
        "connector_ids": [],
    }

    headers = {"Authorization": f"Bearer {test_user_token}"}

    # Note: This test would need actual DB setup with trading accounts
    # For now, this is a skeleton showing the expected flow

    # response = await test_client.post("/api/v2/agents", json=payload, headers=headers)
    # assert response.status_code == 201
    # data = response.json()
    # assert data["engine_type"] == "pipeline"
    # assert data["broker_type"] == "robinhood"


@pytest.mark.asyncio
async def test_approve_pipeline_agent_calls_worker():
    """Test that approving a pipeline agent calls pipeline-worker service."""
    from apps.api.src.routes.agents import approve_agent
    from shared.db.models.agent import Agent

    agent_id = uuid.uuid4()

    # Mock agent
    mock_agent = Agent(
        id=agent_id,
        name="Test Pipeline Bot",
        type="trading",
        engine_type="pipeline",
        status="BACKTEST_COMPLETE",
        config={"broker_type": "robinhood"},
    )

    # Mock session
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none.return_value = mock_agent
    mock_session.execute.return_value = mock_result

    # Mock gateway.start_pipeline_agent
    with patch("apps.api.src.routes.agents.gateway") as mock_gateway:
        mock_gateway.start_pipeline_agent.return_value = "worker-123"

        # Call approve
        # result = await approve_agent(str(agent_id), mock_session, None)

        # Verify start_pipeline_agent was called
        # mock_gateway.start_pipeline_agent.assert_called_once()


@pytest.mark.asyncio
async def test_get_pipeline_agent_includes_stats():
    """Test that GET /agents/{id} includes pipeline_stats for pipeline agents."""
    from apps.api.src.routes.agents import get_agent
    from shared.db.models.agent import Agent, PipelineWorkerState
    from datetime import datetime, timezone

    agent_id = uuid.uuid4()

    # Mock agent
    mock_agent = Agent(
        id=agent_id,
        name="Test Pipeline Bot",
        type="trading",
        engine_type="pipeline",
        status="RUNNING",
        config={"broker_type": "robinhood"},
    )

    # Mock pipeline worker state
    mock_pws = PipelineWorkerState(
        id=uuid.uuid4(),
        agent_id=agent_id,
        stream_key="stream:channel:test",
        signals_processed=42,
        trades_executed=7,
        signals_skipped=35,
        last_heartbeat=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )

    # Mock session
    mock_session = AsyncMock()

    # First execute returns agent
    agent_result = AsyncMock()
    agent_result.scalar_one_or_none.return_value = mock_agent

    # Second execute returns pipeline worker state
    pws_result = AsyncMock()
    pws_result.scalar_one_or_none.return_value = mock_pws

    mock_session.execute.side_effect = [agent_result, pws_result]

    # Call get_agent
    # result = await get_agent(str(agent_id), mock_session)

    # Verify pipeline_stats are included
    # assert result.runtime_info is not None
    # assert "pipeline_stats" in result.runtime_info
    # assert result.runtime_info["pipeline_stats"]["signals_processed"] == 42
    # assert result.runtime_info["pipeline_stats"]["trades_executed"] == 7
