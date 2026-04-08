"""Unit tests for Robinhood MCP server wiring in live agent provisioning."""
import json


def _get_write_fn():
    from apps.api.src.services.agent_gateway import _write_claude_settings
    return _write_claude_settings


def test_write_claude_settings_with_credentials(tmp_path):
    """_write_claude_settings with credentials writes robinhood MCP entry."""
    rh_creds = {
        "username": "user@example.com",
        "password": "s3cr3t",
        "totp_secret": "ABCDEF123456",
    }
    fn = _get_write_fn()
    fn(tmp_path, rh_creds, paper_mode=True)

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists(), ".claude/settings.json should be written"

    settings = json.loads(settings_path.read_text())
    assert "robinhood" in settings["mcpServers"], "robinhood MCP entry must be present"

    rh_env = settings["mcpServers"]["robinhood"]["env"]
    assert rh_env["RH_USERNAME"] == "user@example.com"
    assert rh_env["RH_PASSWORD"] == "s3cr3t"
    assert rh_env["RH_TOTP_SECRET"] == "ABCDEF123456"
    assert rh_env["ROBINHOOD_CONFIG"] == "config.json"
    assert rh_env["PAPER_MODE"] == "true"


def test_write_claude_settings_without_credentials(tmp_path):
    """_write_claude_settings with empty creds still writes MCP entry in paper mode."""
    fn = _get_write_fn()
    fn(tmp_path, rh_creds={}, paper_mode=True)

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists()

    settings = json.loads(settings_path.read_text())
    # MCP entry is ALWAYS present (paper mode runs with PAPER_MODE=true, no real API calls)
    assert "robinhood" in settings["mcpServers"], "MCP entry must be present even without creds (paper mode)"
    rh_env = settings["mcpServers"]["robinhood"]["env"]
    assert rh_env["PAPER_MODE"] == "true"
    assert rh_env["ROBINHOOD_CONFIG"] == "config.json"
    # No real credentials in env
    assert "RH_USERNAME" not in rh_env
    assert "RH_PASSWORD" not in rh_env
    assert "RH_TOTP_SECRET" not in rh_env


def test_write_claude_settings_live_mode(tmp_path):
    """paper_mode=False sets PAPER_MODE=false in the env."""
    rh_creds = {"username": "u", "password": "p", "totp_secret": "T"}
    fn = _get_write_fn()
    fn(tmp_path, rh_creds, paper_mode=False)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["mcpServers"]["robinhood"]["env"]["PAPER_MODE"] == "false"


def test_write_claude_settings_idempotent(tmp_path):
    """Calling _write_claude_settings twice overwrites cleanly."""
    rh_creds = {"username": "u", "password": "p", "totp_secret": "T"}
    fn = _get_write_fn()
    fn(tmp_path, rh_creds, paper_mode=True)
    fn(tmp_path, rh_creds, paper_mode=False)  # second call

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["mcpServers"]["robinhood"]["env"]["PAPER_MODE"] == "false"


def test_write_claude_settings_permissions(tmp_path):
    """Written settings include allow/deny permissions."""
    fn = _get_write_fn()
    fn(tmp_path, {}, paper_mode=True)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "allow" in settings["permissions"]
    assert "deny" in settings["permissions"]
    assert any("python" in a for a in settings["permissions"]["allow"])


def test_heal_creates_settings_for_existing_agent(tmp_path):
    """_heal_live_agent_claude_settings writes settings.json for agents missing it.

    After M2 the healer delegates to _write_claude_settings, so this test
    exercises that function directly with the exact scenario the healer handles.
    Direct import of main._heal_live_agent_claude_settings is blocked in Python
    3.9 because middleware/auth.py uses the 3.10+ ``dict | None`` union syntax.
    """
    import stat

    # Set up a fake live_agents directory structure under tmp_path
    agent_dir = tmp_path / "live_agents" / "test-agent-123"
    (agent_dir / "tools").mkdir(parents=True)
    (agent_dir / "tools" / "robinhood_mcp.py").write_text("# fake mcp")

    config = {
        "robinhood_credentials": {
            "username": "heal@test.com",
            "password": "healpw",
            "totp_secret": "HEALTOTP",
        },
        "paper_mode": True,
    }
    (agent_dir / "config.json").write_text(json.dumps(config))

    # Reproduce the healer's logic: read config, extract creds, call the delegate
    from apps.api.src.services.agent_gateway import _write_claude_settings

    agent_config = json.loads((agent_dir / "config.json").read_text())
    rh_creds = agent_config.get("robinhood_credentials") or agent_config.get("robinhood") or {}
    paper_mode = agent_config.get("paper_mode", True)

    _write_claude_settings(agent_dir, rh_creds, paper_mode=bool(paper_mode))

    settings_path = agent_dir / ".claude" / "settings.json"
    assert settings_path.exists(), ".claude/settings.json should be written"

    written = json.loads(settings_path.read_text())
    assert "robinhood" in written["mcpServers"], "robinhood MCP entry must be present"

    env = written["mcpServers"]["robinhood"]["env"]
    assert env["RH_USERNAME"] == "heal@test.com"
    assert env["RH_PASSWORD"] == "healpw"
    assert env["RH_TOTP_SECRET"] == "HEALTOTP"
    assert env["PAPER_MODE"] == "true"

    # M1: verify the file is owner-only readable (0o600)
    mode = stat.S_IMODE(settings_path.stat().st_mode)
    assert mode == 0o600, f"Expected 0o600 (owner-only), got {oct(mode)}"

    # Permissions must include MCP tool wildcard
    assert "mcp__robinhood__*" in written["permissions"]["allow"]


def test_write_claude_settings_allows_mcp_tools(tmp_path):
    """Written settings include mcp__robinhood__* in the allow list."""
    fn = _get_write_fn()
    fn(tmp_path, {}, paper_mode=True)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    allow_list = settings["permissions"]["allow"]
    assert "mcp__robinhood__*" in allow_list, "mcp__robinhood__* must be in allow list"


def test_write_claude_settings_uses_sys_executable(tmp_path):
    """MCP server command uses sys.executable (the venv Python), not bare python3."""
    import sys
    fn = _get_write_fn()
    fn(tmp_path, {}, paper_mode=True)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    command = settings["mcpServers"]["robinhood"]["command"]
    assert command == sys.executable, (
        f"MCP server command should be sys.executable ({sys.executable!r}), got {command!r}"
    )


def test_write_claude_settings_paper_mode_no_credentials_in_env(tmp_path):
    """Paper-only agents (no creds) should NOT have RH credentials in MCP env."""
    fn = _get_write_fn()
    fn(tmp_path, rh_creds={}, paper_mode=True)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    rh_env = settings["mcpServers"]["robinhood"]["env"]
    assert "RH_USERNAME" not in rh_env
    assert "RH_PASSWORD" not in rh_env
    assert "RH_TOTP_SECRET" not in rh_env
    assert rh_env["PAPER_MODE"] == "true"


def test_write_claude_settings_live_mode_has_credentials_in_env(tmp_path):
    """Live agents with credentials should have RH credentials in MCP env."""
    rh_creds = {"username": "trader@example.com", "password": "s3cr3t", "totp_secret": "TOTP123"}
    fn = _get_write_fn()
    fn(tmp_path, rh_creds=rh_creds, paper_mode=False)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    rh_env = settings["mcpServers"]["robinhood"]["env"]
    assert rh_env["RH_USERNAME"] == "trader@example.com"
    assert rh_env["RH_PASSWORD"] == "s3cr3t"
    assert rh_env["RH_TOTP_SECRET"] == "TOTP123"
    assert rh_env["PAPER_MODE"] == "false"
    assert rh_env["ROBINHOOD_CONFIG"] == "config.json"


def test_heal_missing_settings_paper_agent_gets_mcp_entry(tmp_path):
    """Healing a paper agent (no creds) writes settings WITH MCP entry."""
    import stat

    agent_dir = tmp_path / "live_agents" / "paper-agent-456"
    (agent_dir / "tools").mkdir(parents=True)
    (agent_dir / "tools" / "robinhood_mcp.py").write_text("# fake mcp")

    config = {
        "robinhood_credentials": {},
        "paper_mode": True,
    }
    (agent_dir / "config.json").write_text(json.dumps(config))

    from apps.api.src.services.agent_gateway import _write_claude_settings

    rh_creds = config.get("robinhood_credentials") or {}
    paper_mode = config.get("paper_mode", True)
    _write_claude_settings(agent_dir, rh_creds, paper_mode=bool(paper_mode))

    settings_path = agent_dir / ".claude" / "settings.json"
    assert settings_path.exists()
    written = json.loads(settings_path.read_text())

    # Paper agents MUST have MCP entry so they can simulate trades
    assert "robinhood" in written["mcpServers"], "Paper agent must have robinhood MCP entry"
    env = written["mcpServers"]["robinhood"]["env"]
    assert env["PAPER_MODE"] == "true"
    assert "RH_USERNAME" not in env  # no real credentials

    # Permissions must allow MCP tools
    assert "mcp__robinhood__*" in written["permissions"]["allow"]

    # File permissions: owner-only readable
    mode = stat.S_IMODE(settings_path.stat().st_mode)
    assert mode == 0o600
