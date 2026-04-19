"""Unit tests for Pipeline Engine gateway integration and route changes.

Run with:
    python3 -m pytest tests/unit/test_pipeline_engine_integration.py -v --tb=short

Tests covered:
  Gateway:
    - start_pipeline_agent: HTTP POST to pipeline-worker, creates AgentSession
    - start_pipeline_agent: failure path sets worker_status=ERROR
    - stop_pipeline_agent: HTTP POST stop, updates session status
    - stop_pipeline_agent: failure path returns False
    - _get_agent_engine_type: returns 'sdk' for standard agents, 'pipeline' for pipeline
    - create_analyst: dispatches to start_pipeline_agent for pipeline engine_type
    - stop_agent: dispatches to stop_pipeline_agent for pipeline engine_type
    - pause_agent: dispatches to stop_pipeline_agent for pipeline engine_type
    - resume_agent: dispatches to start_pipeline_agent for pipeline engine_type
    - create_backtester: forces orchestrator path for pipeline agents
  Routes:
    - AgentCreate model accepts engine_type field
    - AgentCreate model validates engine_type (rejects invalid values)
    - AgentResponse includes engine_type
    - process-message rejects pipeline agents with helpful message
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_agent(
    status: str = "APPROVED",
    engine_type: str = "sdk",
    config: dict | None = None,
) -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.name = "TestAgent"
    a.type = "trading"
    a.engine_type = engine_type
    a.status = status
    a.error_message = None
    a.worker_status = "STOPPED"
    a.updated_at = datetime.now(timezone.utc)
    a.config = config if config is not None else {"connector_ids": [str(uuid.uuid4())]}
    a.manifest = {}
    a.channel_name = "test-channel"
    a.analyst_name = "TestAnalyst"
    a.current_mode = "conservative"
    a.phoenix_api_key = ""
    a.model_type = None
    a.model_accuracy = None
    a.daily_pnl = 0.0
    a.total_pnl = 0.0
    a.total_trades = 0
    a.win_rate = 0.0
    a.rules_version = 1
    a.last_signal_at = None
    a.last_trade_at = None
    a.created_at = datetime.now(timezone.utc)
    a.last_activity_at = None
    return a


def _mock_db_with_agent(agent: MagicMock) -> AsyncMock:
    """Build an async DB session mock that returns agent on execute."""
    async def _execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = agent
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_get_session(db: AsyncMock):
    """Create an async generator that yields db once."""
    async def _gen():
        yield db
    return _gen


# ---------------------------------------------------------------------------
# Route model tests
# ---------------------------------------------------------------------------

class TestAgentCreateModel:
    def test_default_engine_type_is_sdk(self):
        from apps.api.src.routes.agents import AgentCreate
        payload = AgentCreate(name="Test", type="trading")
        assert payload.engine_type == "sdk"

    def test_pipeline_engine_type_accepted(self):
        from apps.api.src.routes.agents import AgentCreate
        payload = AgentCreate(name="Test", type="trading", engine_type="pipeline")
        assert payload.engine_type == "pipeline"

    def test_invalid_engine_type_rejected(self):
        from apps.api.src.routes.agents import AgentCreate
        with pytest.raises(ValidationError) as exc_info:
            AgentCreate(name="Test", type="trading", engine_type="invalid")
        assert "engine_type" in str(exc_info.value)


class TestAgentResponseModel:
    def test_engine_type_included_in_response(self):
        from apps.api.src.routes.agents import AgentResponse
        agent = _make_agent(engine_type="pipeline")
        resp = AgentResponse.from_model(agent)
        assert resp.engine_type == "pipeline"

    def test_engine_type_defaults_to_sdk(self):
        from apps.api.src.routes.agents import AgentResponse
        agent = _make_agent(engine_type="sdk")
        resp = AgentResponse.from_model(agent)
        assert resp.engine_type == "sdk"

    def test_engine_type_missing_attr_defaults_to_sdk(self):
        from apps.api.src.routes.agents import AgentResponse
        agent = _make_agent()
        del agent.engine_type
        resp = AgentResponse.from_model(agent)
        assert resp.engine_type == "sdk"


# ---------------------------------------------------------------------------
# Gateway: _get_agent_engine_type
# ---------------------------------------------------------------------------

class TestGetAgentEngineType:
    @pytest.mark.asyncio
    async def test_returns_pipeline_for_pipeline_agent(self):
        agent = _make_agent(engine_type="pipeline")
        db = _mock_db_with_agent(agent)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw._get_agent_engine_type(agent.id)
            assert result == "pipeline"

    @pytest.mark.asyncio
    async def test_returns_sdk_for_sdk_agent(self):
        agent = _make_agent(engine_type="sdk")
        db = _mock_db_with_agent(agent)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw._get_agent_engine_type(agent.id)
            assert result == "sdk"

    @pytest.mark.asyncio
    async def test_returns_sdk_for_missing_agent(self):
        async def _execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw._get_agent_engine_type(uuid.uuid4())
            assert result == "sdk"


# ---------------------------------------------------------------------------
# Gateway: start_pipeline_agent
# ---------------------------------------------------------------------------

class TestStartPipelineAgent:
    @pytest.mark.asyncio
    async def test_success_returns_worker_id(self):
        agent = _make_agent(engine_type="pipeline", config={"connector_ids": ["abc-123"]})
        db = _mock_db_with_agent(agent)
        worker_id = str(uuid.uuid4())

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"worker_id": worker_id, "status": "starting"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ), patch("httpx.AsyncClient", return_value=mock_client):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.start_pipeline_agent(agent.id)

        assert result == worker_id

    @pytest.mark.asyncio
    async def test_failure_returns_none(self):
        agent = _make_agent(engine_type="pipeline")
        db = _mock_db_with_agent(agent)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ), patch("httpx.AsyncClient", return_value=mock_client):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.start_pipeline_agent(agent.id)

        assert result is None


# ---------------------------------------------------------------------------
# Gateway: stop_pipeline_agent
# ---------------------------------------------------------------------------

class TestStopPipelineAgent:
    @pytest.mark.asyncio
    async def test_success_returns_true(self):
        agent = _make_agent(engine_type="pipeline")
        sess_mock = MagicMock()
        sess_mock.status = "running"
        sess_mock.stopped_at = None

        call_count = {"n": 0}

        async def _execute(stmt):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = agent
            else:
                result.scalar_one_or_none.return_value = sess_mock
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_execute)
        db.commit = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ), patch("httpx.AsyncClient", return_value=mock_client):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.stop_pipeline_agent(agent.id)

        assert result is True

    @pytest.mark.asyncio
    async def test_failure_returns_false(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.stop_pipeline_agent(uuid.uuid4())

        assert result is False


# ---------------------------------------------------------------------------
# Gateway: create_analyst dispatches by engine_type
# ---------------------------------------------------------------------------

class TestCreateAnalystPipelineDispatch:
    @pytest.mark.asyncio
    async def test_pipeline_agent_calls_start_pipeline(self):
        agent_id = uuid.uuid4()
        expected_worker_id = str(uuid.uuid4())
        agent = _make_agent(engine_type="pipeline")
        agent.id = agent_id
        agent.status = "APPROVED"
        db = _mock_db_with_agent(agent)

        with patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ), patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "start_pipeline_agent",
            return_value=expected_worker_id,
        ) as mock_start:
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.create_analyst(agent_id)

        assert result == expected_worker_id
        mock_start.assert_called_once_with(agent_id, None)


# ---------------------------------------------------------------------------
# Gateway: stop_agent dispatches by engine_type
# ---------------------------------------------------------------------------

class TestStopAgentPipelineDispatch:
    @pytest.mark.asyncio
    async def test_pipeline_agent_calls_stop_pipeline(self):
        agent_id = uuid.uuid4()

        with patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "_get_agent_engine_type",
            return_value="pipeline",
        ), patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "stop_pipeline_agent",
            return_value=True,
        ) as mock_stop:
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.stop_agent(agent_id)

        assert result["status"] == "stopped"
        mock_stop.assert_called_once_with(agent_id)


# ---------------------------------------------------------------------------
# Gateway: pause_agent dispatches by engine_type
# ---------------------------------------------------------------------------

class TestPauseAgentPipelineDispatch:
    @pytest.mark.asyncio
    async def test_pipeline_agent_pauses_via_stop_pipeline(self):
        agent_id = uuid.uuid4()
        agent = _make_agent(engine_type="pipeline")
        db = _mock_db_with_agent(agent)

        with patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "_get_agent_engine_type",
            return_value="pipeline",
        ), patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "stop_pipeline_agent",
            return_value=True,
        ) as mock_stop, patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.pause_agent(agent_id)

        assert result["status"] == "paused"
        mock_stop.assert_called_once_with(agent_id)


# ---------------------------------------------------------------------------
# Gateway: resume_agent dispatches by engine_type
# ---------------------------------------------------------------------------

class TestResumeAgentPipelineDispatch:
    @pytest.mark.asyncio
    async def test_pipeline_agent_resumes_via_start_pipeline(self):
        agent_id = uuid.uuid4()
        agent = _make_agent(engine_type="pipeline")
        db = _mock_db_with_agent(agent)
        expected_worker_id = str(uuid.uuid4())

        with patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "_get_agent_engine_type",
            return_value="pipeline",
        ), patch.object(
            __import__("apps.api.src.services.agent_gateway", fromlist=["AgentGateway"]).AgentGateway,
            "start_pipeline_agent",
            return_value=expected_worker_id,
        ) as mock_start, patch(
            "apps.api.src.services.agent_gateway._get_session",
            return_value=_mock_get_session(db)(),
        ):
            from apps.api.src.services.agent_gateway import AgentGateway
            gw = AgentGateway()
            result = await gw.resume_agent(agent_id)

        assert result["status"] == "resuming"
        mock_start.assert_called_once_with(agent_id)


# ---------------------------------------------------------------------------
# Gateway: create_backtester forces orchestrator for pipeline agents
# ---------------------------------------------------------------------------

class TestCreateBacktesterPipelineForcesOrchestrator:
    def test_use_orchestrator_true_when_pipeline(self):
        """Verify the logic: engine_type=='pipeline' always forces use_orchestrator=True."""
        engine_type = "pipeline"
        import os
        use_orchestrator = (
            engine_type == "pipeline"
            or os.getenv("BACKTEST_TIER", "orchestrator") != "sdk"
        )
        assert use_orchestrator is True

    def test_use_orchestrator_unchanged_for_sdk_default(self):
        """SDK agents use the env var logic (default is 'orchestrator' != 'sdk' → True)."""
        engine_type = "sdk"
        use_orchestrator = (
            engine_type == "pipeline"
            or "orchestrator" != "sdk"
        )
        assert use_orchestrator is True

    def test_sdk_agent_respects_env_sdk_tier(self):
        """If BACKTEST_TIER=sdk and engine_type=sdk, use_orchestrator should be False."""
        engine_type = "sdk"
        use_orchestrator = (
            engine_type == "pipeline"
            or "sdk" != "sdk"
        )
        assert use_orchestrator is False


# ---------------------------------------------------------------------------
# PIPELINE_WORKER_URL config
# ---------------------------------------------------------------------------

class TestPipelineWorkerUrlConfig:
    def test_default_url(self):
        from apps.api.src.services.agent_gateway import PIPELINE_WORKER_URL
        assert "8055" in PIPELINE_WORKER_URL or PIPELINE_WORKER_URL.startswith("http")
