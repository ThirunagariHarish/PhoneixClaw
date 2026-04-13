"""Unit tests for orchestrator_proxy module."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level _client between tests."""
    import apps.api.src.services.orchestrator_proxy as mod
    mod._client = None
    yield
    mod._client = None


class TestGetClient:
    def test_creates_client_when_none(self):
        from apps.api.src.services.orchestrator_proxy import _get_client
        client = _get_client()
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed

    def test_reuses_existing_client(self):
        from apps.api.src.services.orchestrator_proxy import _get_client
        c1 = _get_client()
        c2 = _get_client()
        assert c1 is c2

    def test_recreates_if_closed(self):
        import apps.api.src.services.orchestrator_proxy as mod
        from apps.api.src.services.orchestrator_proxy import _get_client
        c1 = _get_client()
        mod._client = MagicMock(is_closed=True)
        c2 = _get_client()
        assert c2 is not c1


class TestStartAgent:
    @pytest.mark.asyncio
    async def test_start_agent_success(self):
        from apps.api.src.services.orchestrator_proxy import start_agent
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "started"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("apps.api.src.services.orchestrator_proxy._get_client", return_value=mock_client):
            result = await start_agent("agent-1", {"key": "val"})

        assert result == {"status": "started"}
        mock_client.post.assert_called_once_with("/agents/agent-1/start", json={"key": "val"})

    @pytest.mark.asyncio
    async def test_start_agent_raises_on_error(self):
        from apps.api.src.services.orchestrator_proxy import start_agent
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.is_closed = False

        with patch("apps.api.src.services.orchestrator_proxy._get_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await start_agent("agent-1")


class TestStopAgent:
    @pytest.mark.asyncio
    async def test_stop_agent_success(self):
        from apps.api.src.services.orchestrator_proxy import stop_agent
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "stopped"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("apps.api.src.services.orchestrator_proxy._get_client", return_value=mock_client):
            result = await stop_agent("agent-2")

        assert result == {"status": "stopped"}
        mock_client.post.assert_called_once_with("/agents/agent-2/stop")


class TestResumeAgent:
    @pytest.mark.asyncio
    async def test_resume_agent_success(self):
        from apps.api.src.services.orchestrator_proxy import resume_agent
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "resumed"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("apps.api.src.services.orchestrator_proxy._get_client", return_value=mock_client):
            result = await resume_agent("agent-3")

        assert result == {"status": "resumed"}
        mock_client.post.assert_called_once_with("/agents/agent-3/resume")


class TestGetAgentStatus:
    @pytest.mark.asyncio
    async def test_get_agent_status_success(self):
        from apps.api.src.services.orchestrator_proxy import get_agent_status
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "running", "uptime": 300}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("apps.api.src.services.orchestrator_proxy._get_client", return_value=mock_client):
            result = await get_agent_status("agent-4")

        assert result == {"status": "running", "uptime": 300}

    @pytest.mark.asyncio
    async def test_get_agent_status_returns_unknown_on_error(self):
        from apps.api.src.services.orchestrator_proxy import get_agent_status
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.is_closed = False

        with patch("apps.api.src.services.orchestrator_proxy._get_client", return_value=mock_client):
            result = await get_agent_status("agent-4")

        assert result["status"] == "unknown"
        assert "error" in result
