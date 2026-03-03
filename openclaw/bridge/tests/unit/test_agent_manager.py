"""Agent workspace CRUD. M1.7."""
import tempfile
import pytest

# Run with AGENTS_ROOT set to temp dir
@pytest.fixture
def agents_root(tmp_path, monkeypatch):
    monkeypatch.setattr("src.agent_manager.settings", type("S", (), {"AGENTS_ROOT": str(tmp_path)})())
    monkeypatch.setattr("src.agent_manager.AGENTS_ROOT", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_create_agent_writes_config_files(agents_root):
    from src.agent_manager import create_agent, _agent_dir
    create_agent("test-agent", "Test Agent", "trading", {"key": "value"})
    d = _agent_dir("test-agent")
    assert (d / "AGENTS.md").exists()
    assert (d / "TOOLS.md").exists()
    assert (d / "SOUL.md").exists()
    assert (d / "HEARTBEAT.md").exists()
    assert (d / "config.json").exists()
    assert (d / "status.json").exists()


def test_delete_agent_removes_workspace(agents_root):
    from src.agent_manager import create_agent, delete_agent, _agent_dir
    create_agent("to-delete", "To Delete", "trading")
    assert _agent_dir("to-delete").exists()
    delete_agent("to-delete")
    assert not _agent_dir("to-delete").exists()


def test_list_agents(agents_root):
    from src.agent_manager import create_agent, list_agents
    create_agent("a1", "Agent 1", "trading")
    create_agent("a2", "Agent 2", "monitoring")
    agents = list_agents()
    assert len(agents) == 2
    ids = {a["id"] for a in agents}
    assert "a1" in ids and "a2" in ids


def test_get_agent_detail(agents_root):
    from src.agent_manager import create_agent, get_agent
    create_agent("detail-agent", "Detail", "trading")
    a = get_agent("detail-agent")
    assert a is not None
    assert a["id"] == "detail-agent"
    assert a["status"] == "CREATED"


def test_pause_agent(agents_root):
    from src.agent_manager import create_agent, set_agent_status, get_agent
    create_agent("pause-me", "Pause Me", "trading")
    set_agent_status("pause-me", "PAUSED")
    a = get_agent("pause-me")
    assert a["status"] == "PAUSED"


def test_resume_agent(agents_root):
    from src.agent_manager import create_agent, set_agent_status, get_agent
    create_agent("resume-me", "Resume Me", "trading")
    set_agent_status("resume-me", "PAUSED")
    set_agent_status("resume-me", "RUNNING")
    a = get_agent("resume-me")
    assert a["status"] == "RUNNING"
