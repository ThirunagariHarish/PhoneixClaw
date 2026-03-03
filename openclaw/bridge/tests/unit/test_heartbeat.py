"""Heartbeat collector. M1.7."""
import pytest


@pytest.fixture
def mock_list_agents(monkeypatch):
    data = [
        {"id": "a1", "name": "Agent 1", "status": "RUNNING", "pnl": 100},
        {"id": "a2", "name": "Agent 2", "status": "PAUSED", "pnl": 0},
    ]
    monkeypatch.setattr("src.heartbeat.list_agents", lambda: data)


def test_collect_heartbeat_returns_all_agents(mock_list_agents):
    from src.heartbeat import collect_heartbeat
    out = collect_heartbeat()
    assert "agents" in out
    assert out["count"] == 2
    assert len(out["agents"]) == 2


def test_heartbeat_includes_status_and_pnl(mock_list_agents):
    from src.heartbeat import collect_heartbeat
    out = collect_heartbeat()
    a1 = next(a for a in out["agents"] if a["id"] == "a1")
    assert a1["status"] == "RUNNING"
    assert a1["pnl"] == 100
