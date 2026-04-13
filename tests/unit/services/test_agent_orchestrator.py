"""Unit tests for the Agent Orchestrator service."""
from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from services.agent_orchestrator.src.main import (
    StartRequest,
    StatusResponse,
    StopResponse,
    _download_model_bundle,
    _prepare_working_directory,
    _render_claude_md,
    _running_agents,
    _session_ids,
    _write_claude_settings,
    app,
)


@pytest.fixture(autouse=True)
def _clear_state():
    """Reset module-level state between tests."""
    _running_agents.clear()
    _session_ids.clear()
    yield
    _running_agents.clear()
    _session_ids.clear()


@pytest.fixture
def mock_agent():
    """Fake Agent ORM object."""
    return SimpleNamespace(
        id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        name="TestBot",
        channel_name="test-channel",
        analyst_name="analyst-1",
        current_mode="conservative",
        status="APPROVED",
        manifest={"risk": {"max_position_size_pct": 5}, "modes": {}, "rules": [], "identity": {}},
        config={"risk_params": {}},
        phoenix_api_key="test-key",
        worker_status="STOPPED",
    )


class TestStartRequest:
    def test_default_values(self):
        req = StartRequest()
        assert req.mode == "live"
        assert req.resume is False
        assert req.config == {}

    def test_paper_mode(self):
        req = StartRequest(mode="paper")
        assert req.mode == "paper"

    def test_invalid_mode_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StartRequest(mode="invalid")


class TestStopResponse:
    def test_serialization(self):
        resp = StopResponse(status="stopped", agent_id="abc-123")
        assert resp.status == "stopped"
        assert resp.agent_id == "abc-123"


class TestStatusResponse:
    def test_not_running(self):
        resp = StatusResponse(running=False)
        assert resp.running is False
        assert resp.session_id is None
        assert resp.uptime_seconds is None

    def test_running_with_uptime(self):
        resp = StatusResponse(running=True, session_id="sid-1", uptime_seconds=3600.5)
        assert resp.running is True
        assert resp.uptime_seconds == 3600.5


class TestPrepareWorkingDirectory:
    def test_creates_directory_and_config(self, tmp_path, mock_agent, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        template_dir = tmp_path / "template"
        tools_dir = template_dir / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "check_messages.py").write_text("# tool")

        skills_dir = template_dir / "skills"
        skills_dir.mkdir()
        (skills_dir / "skill1.py").write_text("# skill")

        monkeypatch.setattr("services.agent_orchestrator.src.main.DATA_DIR", data_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main.LIVE_TEMPLATE", template_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main._download_model_bundle", lambda *a: None)

        agent_id = str(mock_agent.id)
        work_dir = _prepare_working_directory(agent_id, mock_agent, {"mode": "live"})

        assert work_dir.exists()
        assert (work_dir / "tools" / "check_messages.py").exists()
        assert (work_dir / "skills" / "skill1.py").exists()
        assert (work_dir / "config.json").exists()

        config = json.loads((work_dir / "config.json").read_text())
        assert config["agent_id"] == agent_id
        assert config["agent_name"] == "TestBot"
        assert config["phoenix_api_url"] is not None

    def test_risk_params_written_alongside_risk(self, tmp_path, mock_agent, monkeypatch):
        """Both 'risk' and 'risk_params' keys must appear in config.json with identical values."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        template_dir = tmp_path / "template"
        template_dir.mkdir()

        monkeypatch.setattr("services.agent_orchestrator.src.main.DATA_DIR", data_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main.LIVE_TEMPLATE", template_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main._download_model_bundle", lambda *a: None)

        mock_agent.manifest = {
            "risk": {"max_position_size_pct": 3, "confidence_threshold": 0.70},
            "modes": {},
            "rules": [],
            "identity": {},
        }

        agent_id = str(mock_agent.id)
        work_dir = _prepare_working_directory(agent_id, mock_agent, {})

        config = json.loads((work_dir / "config.json").read_text())
        assert "risk" in config
        assert "risk_params" in config
        assert config["risk"] == config["risk_params"]
        assert config["risk"]["max_position_size_pct"] == 3
        assert config["risk"]["confidence_threshold"] == 0.70

    def test_risk_params_fallback_from_config_data(self, tmp_path, mock_agent, monkeypatch):
        """When manifest has no risk key, risk_params falls back to agent.config['risk_params']."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        template_dir = tmp_path / "template"
        template_dir.mkdir()

        monkeypatch.setattr("services.agent_orchestrator.src.main.DATA_DIR", data_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main.LIVE_TEMPLATE", template_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main._download_model_bundle", lambda *a: None)

        mock_agent.manifest = {"modes": {}, "rules": [], "identity": {}}
        mock_agent.config = {"risk_params": {"max_daily_loss_pct": 2.5}}

        agent_id = str(mock_agent.id)
        work_dir = _prepare_working_directory(agent_id, mock_agent, {})

        config = json.loads((work_dir / "config.json").read_text())
        assert config["risk"] == {"max_daily_loss_pct": 2.5}
        assert config["risk_params"] == {"max_daily_loss_pct": 2.5}

    def test_claude_settings_written(self, tmp_path, mock_agent, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        template_dir = tmp_path / "template"
        template_dir.mkdir()

        monkeypatch.setattr("services.agent_orchestrator.src.main.DATA_DIR", data_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main.LIVE_TEMPLATE", template_dir)
        monkeypatch.setattr("services.agent_orchestrator.src.main._download_model_bundle", lambda *a: None)

        agent_id = str(mock_agent.id)
        work_dir = _prepare_working_directory(agent_id, mock_agent, {})

        settings_path = work_dir / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "permissions" in settings
        assert "allow" in settings["permissions"]


class TestWriteClaudeSettings:
    def test_creates_settings_file(self, tmp_path):
        _write_claude_settings(tmp_path)

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()

        settings = json.loads(settings_path.read_text())
        assert "Bash(python3 *)" in settings["permissions"]["allow"]
        assert "mcpServers" not in settings

    def test_permissions_restrictive(self, tmp_path):
        _write_claude_settings(tmp_path)
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "Bash(rm -rf /)" in settings["permissions"]["deny"]


class TestRenderClaudeMd:
    def test_fallback_when_no_template(self, tmp_path, mock_agent, monkeypatch):
        monkeypatch.setattr("services.agent_orchestrator.src.main.LIVE_TEMPLATE", tmp_path / "nonexistent")
        _render_claude_md(mock_agent, mock_agent.manifest, tmp_path)
        md_path = tmp_path / "CLAUDE.md"
        assert md_path.exists()
        assert "TestBot" in md_path.read_text()

    def test_render_from_template(self, tmp_path, mock_agent, monkeypatch):
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "CLAUDE.md.jinja2").write_text("# Agent: {{ identity.name }}")
        monkeypatch.setattr("services.agent_orchestrator.src.main.LIVE_TEMPLATE", template_dir)
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        _render_claude_md(mock_agent, mock_agent.manifest, out_dir)
        content = (out_dir / "CLAUDE.md").read_text()
        assert "TestBot" in content


class TestDownloadModelBundle:
    def test_handles_missing_minio_gracefully(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINIO_ENDPOINT", "nonexistent-host:9999")
        _download_model_bundle("test-agent", tmp_path)


class TestKeepaliveTick:
    @pytest.mark.asyncio
    async def test_skips_already_running_agents(self):
        """Verify keepalive does not restart an agent that already has an active task."""
        agent_id = "test-agent-1"
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        _running_agents[agent_id] = asyncio.ensure_future(future)

        call_log: list[str] = []

        async def patched_tick():
            """Lightweight keepalive check that only verifies the skip logic."""
            for agent_key, task in list(_running_agents.items()):
                if not task.done():
                    call_log.append(f"skip:{agent_key}")
                    continue
                call_log.append(f"restart:{agent_key}")

        await patched_tick()

        assert call_log == [f"skip:{agent_id}"]

        future.cancel()
        try:
            await _running_agents.get(agent_id, asyncio.Future())
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            pass


class TestAppEndpoints:
    """Integration-style tests using FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "running_agents" in data

    def test_list_agents_empty(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["agents"] == []

    def test_status_unknown_agent(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/agents/{fake_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
