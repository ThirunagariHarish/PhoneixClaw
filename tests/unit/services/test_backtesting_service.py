"""Unit tests for the Phoenix backtesting service."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

import services.backtesting.src.main as bt_mod
from services.backtesting.src.main import (
    ApproveRequest,
    BacktestRequest,
    BacktestSummary,
    _active_backtests,
    _prepare_backtest_directory,
    _read_metrics,
    _read_results,
    _write_claude_settings,
    app,
)


@pytest.fixture(autouse=True)
def _clear_state():
    """Reset module-level state between tests."""
    _active_backtests.clear()
    yield
    for entry in list(_active_backtests.values()):
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
    _active_backtests.clear()


@pytest.fixture
def _data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR to a temp directory before any endpoint tests."""
    monkeypatch.setattr(bt_mod, "DATA_DIR", tmp_path / "backtests")
    monkeypatch.setattr(bt_mod, "BACKTEST_TEMPLATE", tmp_path / "template")
    return tmp_path / "backtests"


class TestBacktestRequest:
    def test_default_values(self):
        req = BacktestRequest(agent_id="abc-123")
        assert req.agent_id == "abc-123"
        assert req.config == {}
        assert req.date_range == {}

    def test_with_date_range(self):
        req = BacktestRequest(
            agent_id="abc-123",
            date_range={"start_date": "2025-01-01", "end_date": "2025-06-01"},
        )
        assert req.date_range["start_date"] == "2025-01-01"

    def test_with_config(self):
        req = BacktestRequest(agent_id="abc-123", config={"lookback_days": 90})
        assert req.config["lookback_days"] == 90


class TestApproveRequest:
    def test_default_approved_by(self):
        req = ApproveRequest()
        assert req.approved_by == "system"

    def test_custom_approved_by(self):
        req = ApproveRequest(approved_by="admin-user")
        assert req.approved_by == "admin-user"


class TestBacktestSummary:
    def test_serialization(self):
        summary = BacktestSummary(
            backtest_id="bt-1",
            agent_id="agent-1",
            status="completed",
            created_at="2025-01-01T00:00:00Z",
            finished_at="2025-01-01T01:00:00Z",
        )
        data = summary.model_dump()
        assert data["backtest_id"] == "bt-1"
        assert data["error"] is None

    def test_with_error(self):
        summary = BacktestSummary(
            backtest_id="bt-2",
            agent_id="agent-2",
            status="error",
            created_at="2025-01-01T00:00:00Z",
            error="training failed",
        )
        assert summary.error == "training failed"


class TestPrepareBacktestDirectory:
    def test_creates_directory_and_config(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "backtests"
        data_dir.mkdir()
        template_dir = tmp_path / "template"
        tools_dir = template_dir / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "transform.py").write_text("# tool")

        claude_dir = template_dir / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{}")

        (template_dir / "CLAUDE.md").write_text("# Backtesting Agent")

        monkeypatch.setattr(bt_mod, "DATA_DIR", data_dir)
        monkeypatch.setattr(bt_mod, "BACKTEST_TEMPLATE", template_dir)

        backtest_id = str(uuid.uuid4())
        work_dir = _prepare_backtest_directory(backtest_id, "agent-1", {"lookback_days": 90})

        assert work_dir.exists()
        assert (work_dir / "tools" / "transform.py").exists()
        assert (work_dir / "CLAUDE.md").exists()
        assert (work_dir / "config.json").exists()

        config = json.loads((work_dir / "config.json").read_text())
        assert config["backtest_id"] == backtest_id
        assert config["agent_id"] == "agent-1"
        assert config["lookback_days"] == 90

    def test_overwrites_existing_tools_directory(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "backtests"
        data_dir.mkdir()
        template_dir = tmp_path / "template"
        tools_dir = template_dir / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "new_tool.py").write_text("# new")

        monkeypatch.setattr(bt_mod, "DATA_DIR", data_dir)
        monkeypatch.setattr(bt_mod, "BACKTEST_TEMPLATE", template_dir)

        backtest_id = "existing-bt"
        existing_dir = data_dir / backtest_id / "tools"
        existing_dir.mkdir(parents=True)
        (existing_dir / "old_tool.py").write_text("# old")

        work_dir = _prepare_backtest_directory(backtest_id, "agent-1", {})

        assert (work_dir / "tools" / "new_tool.py").exists()
        assert not (work_dir / "tools" / "old_tool.py").exists()


class TestWriteClaudeSettings:
    def test_creates_settings_file(self, tmp_path):
        _write_claude_settings(tmp_path)

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()

        settings = json.loads(settings_path.read_text())
        assert "Bash(python3 *)" in settings["permissions"]["allow"]

    def test_no_mcp_servers(self, tmp_path):
        _write_claude_settings(tmp_path)
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "mcpServers" not in settings

    def test_permissions_deny_list(self, tmp_path):
        _write_claude_settings(tmp_path)
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "Bash(rm -rf /)" in settings["permissions"]["deny"]


class TestReadMetrics:
    def test_reads_meta_json(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "meta.json").write_text(json.dumps({"accuracy": 0.85}))

        metrics = _read_metrics(tmp_path)
        assert metrics["accuracy"] == 0.85

    def test_falls_back_to_evaluation_results(self, tmp_path):
        (tmp_path / "evaluation_results.json").write_text(json.dumps({"sharpe_ratio": 1.2}))

        metrics = _read_metrics(tmp_path)
        assert metrics["sharpe_ratio"] == 1.2

    def test_returns_empty_when_no_files(self, tmp_path):
        metrics = _read_metrics(tmp_path)
        assert metrics == {}

    def test_handles_invalid_json(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "meta.json").write_text("not valid json{{{")

        metrics = _read_metrics(tmp_path)
        assert metrics == {}


class TestReadResults:
    def test_reads_results_json(self, tmp_path):
        (tmp_path / "backtest_results.json").write_text(json.dumps({"trades": 42}))

        results = _read_results(tmp_path)
        assert results["trades"] == 42

    def test_returns_empty_when_missing(self, tmp_path):
        results = _read_results(tmp_path)
        assert results == {}

    def test_handles_corrupt_json(self, tmp_path):
        (tmp_path / "backtest_results.json").write_text("{broken")
        results = _read_results(tmp_path)
        assert results == {}


class TestAppEndpoints:
    """Integration-style tests using FastAPI TestClient."""

    @pytest.fixture
    def client(self, _data_dir):
        from starlette.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "active_backtests" in data

    def test_list_backtests_empty(self, client):
        resp = client.get("/backtests")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["backtests"] == []

    def test_get_backtest_not_found(self, client):
        resp = client.get(f"/backtests/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_results_not_found(self, client):
        resp = client.get(f"/backtests/{uuid.uuid4()}/results")
        assert resp.status_code == 404

    def test_approve_not_found(self, client):
        resp = client.post(f"/backtests/{uuid.uuid4()}/approve", json={"approved_by": "test"})
        assert resp.status_code == 404

    def test_cancel_not_found(self, client):
        resp = client.delete(f"/backtests/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_create_backtest(self, client):
        resp = client.post("/backtests", json={"agent_id": str(uuid.uuid4())})
        assert resp.status_code == 201
        data = resp.json()
        assert "backtest_id" in data
        assert data["status"] == "pending"

    def test_get_backtest_after_create(self, client):
        create_resp = client.post("/backtests", json={"agent_id": str(uuid.uuid4())})
        bt_id = create_resp.json()["backtest_id"]

        resp = client.get(f"/backtests/{bt_id}")
        assert resp.status_code == 200
        assert resp.json()["backtest_id"] == bt_id

    def test_list_backtests_after_create(self, client):
        client.post("/backtests", json={"agent_id": str(uuid.uuid4())})

        resp = client.get("/backtests")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_cancel_running_backtest(self, client):
        create_resp = client.post("/backtests", json={"agent_id": str(uuid.uuid4())})
        bt_id = create_resp.json()["backtest_id"]

        resp = client.delete(f"/backtests/{bt_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_get_results_before_completion(self, client):
        create_resp = client.post("/backtests", json={"agent_id": str(uuid.uuid4())})
        bt_id = create_resp.json()["backtest_id"]

        _active_backtests[bt_id]["status"] = "running"
        resp = client.get(f"/backtests/{bt_id}/results")
        assert resp.status_code == 200
        assert resp.json()["results"] is None

    def test_approve_wrong_status(self, client):
        create_resp = client.post("/backtests", json={"agent_id": str(uuid.uuid4())})
        bt_id = create_resp.json()["backtest_id"]

        resp = client.post(f"/backtests/{bt_id}/approve", json={"approved_by": "test"})
        assert resp.status_code == 409

    def test_approve_no_bundle(self, client):
        bt_id = str(uuid.uuid4())
        _active_backtests[bt_id] = {
            "backtest_id": bt_id,
            "agent_id": "agent-1",
            "status": "completed",
            "created_at": "2025-01-01T00:00:00Z",
            "finished_at": "2025-01-01T01:00:00Z",
            "error": None,
            "bundle_id": None,
            "session_id": None,
            "results": {},
            "work_dir": "/tmp/fake",
        }

        resp = client.post(f"/backtests/{bt_id}/approve", json={"approved_by": "test"})
        assert resp.status_code == 409
        assert "No model bundle" in resp.json()["detail"]


class TestRunBacktestStub:
    @pytest.mark.asyncio
    async def test_stub_completes_gracefully(self, tmp_path):
        """When claude_agent_sdk is unavailable, the stub path should complete without errors."""
        from services.backtesting.src.main import _run_backtest

        backtest_id = str(uuid.uuid4())
        work_dir = tmp_path / backtest_id
        work_dir.mkdir(parents=True)

        entry = {
            "backtest_id": backtest_id,
            "agent_id": "agent-1",
            "status": "pending",
            "created_at": "2025-01-01T00:00:00Z",
            "finished_at": None,
            "error": None,
            "bundle_id": None,
            "session_id": None,
            "results": {},
            "work_dir": str(work_dir),
        }
        _active_backtests[backtest_id] = entry

        mock_upload = AsyncMock(return_value=None)
        with patch.object(bt_mod, "_upload_bundle", mock_upload):
            await _run_backtest(backtest_id, "agent-1", work_dir)

        assert entry["status"] == "completed"
        assert entry["finished_at"] is not None
