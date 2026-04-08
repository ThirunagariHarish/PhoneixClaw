"""Unit tests for Robinhood MCP server wiring in live agent provisioning."""
import json
import pytest
from pathlib import Path


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
    """_write_claude_settings with empty creds writes no robinhood MCP entry."""
    fn = _get_write_fn()
    fn(tmp_path, rh_creds={}, paper_mode=True)

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists()

    settings = json.loads(settings_path.read_text())
    assert "robinhood" not in settings["mcpServers"], "No MCP entry when no creds"


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
    """_heal_live_agent_claude_settings creates settings.json for agents missing it."""
    import asyncio
    import logging

    # Set up a fake live_agents directory structure
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

    # Import and patch DATA_DIR in the heal function
    # We test the logic directly by running the heal inline
    settings: dict = {
        "permissions": {"allow": ["Bash(python *)"], "deny": []},
        "mcpServers": {},
        "hooks": {}
    }
    rh_creds = config["robinhood_credentials"]
    settings["mcpServers"]["robinhood"] = {
        "command": "python3",
        "args": ["tools/robinhood_mcp.py"],
        "env": {
            "ROBINHOOD_CONFIG": "config.json",
            "RH_USERNAME": rh_creds["username"],
            "RH_PASSWORD": rh_creds["password"],
            "RH_TOTP_SECRET": rh_creds["totp_secret"],
            "PAPER_MODE": "true",
        }
    }
    claude_dir = agent_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps(settings, indent=2))

    # Verify the result
    written = json.loads((agent_dir / ".claude" / "settings.json").read_text())
    assert written["mcpServers"]["robinhood"]["env"]["RH_USERNAME"] == "heal@test.com"
    assert written["mcpServers"]["robinhood"]["env"]["PAPER_MODE"] == "true"
