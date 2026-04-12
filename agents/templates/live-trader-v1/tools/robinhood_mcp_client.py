"""Thin client for the Robinhood MCP server (robinhood_mcp.py).

Launches the MCP server as a subprocess and communicates via stdio JSON-RPC.
Reusable by market_session_gate, paper_portfolio, or any agent tool that needs
to interact with Robinhood through the MCP server.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent
_MCP_SCRIPT = TOOLS_DIR / "robinhood_mcp.py"


class RobinhoodMCPClient:
    """Manages a robinhood_mcp.py subprocess and exposes JSON-RPC calls."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._proc: subprocess.Popen | None = None
        self._request_id = 0

    def _build_env(self) -> dict:
        import os
        env = os.environ.copy()
        creds = self._config.get("robinhood_credentials", self._config.get("robinhood", {}))
        if isinstance(creds, dict):
            # Only override env vars when the config actually supplies a value.
            # Previously, empty-string default values clobbered valid RH_*
            # env vars that were already set in the container/parent process —
            # causing "robinhood_login ✅, everything else ❌" because the
            # subprocess lost the real credentials.
            if creds.get("username"):
                env["RH_USERNAME"] = creds["username"]
            if creds.get("password"):
                env["RH_PASSWORD"] = creds["password"]
            if creds.get("totp_secret"):
                env["RH_TOTP_SECRET"] = creds["totp_secret"]
        if self._config.get("paper_mode"):
            env["PAPER_MODE"] = "true"
        # Always set HOME to the agent work-dir (parent of tools/) so the
        # session pickle at ~/.tokens/{name}.pickle lands on the agent's
        # persistent volume and survives container restarts.
        env["HOME"] = str(_MCP_SCRIPT.parent.parent)
        # NOTE: RH_PASSWORD is present in the subprocess environment because
        # the MCP server's _load_credentials() falls back to env vars when no
        # config.json is present.  Subprocess env vars are visible via
        # /proc/<pid>/environ on Linux — mitigate by using a temp config file
        # with ROBINHOOD_CONFIG pointing to it (already supported) for
        # production deployments where process isolation is a concern.
        return env

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            [sys.executable, str(_MCP_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self._build_env(),
        )
        t = threading.Thread(target=self._drain_stderr, daemon=True)
        t.start()
        log.debug("MCP server started (pid=%d)", self._proc.pid)

    def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        for line in self._proc.stderr:
            log.debug("[mcp-stderr] %s", line.rstrip())

    def call(self, tool_name: str, arguments: dict, timeout: int = 30) -> dict:
        if not self._proc or self._proc.poll() is not None:
            self.start()
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        assert self._proc and self._proc.stdin and self._proc.stdout
        # Scrub sensitive keys before logging so passwords/TOTP codes never
        # reach log files even when DEBUG=1 is set.
        _SENSITIVE = frozenset({"password", "mfa_code", "totp_secret", "access_token"})
        safe_args = {k: "***" if k in _SENSITIVE else v for k, v in arguments.items()}
        log.debug("→ MCP request #%d: %s(%s)", self._request_id, tool_name, json.dumps(safe_args))
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()

        start = time.time()
        while time.time() - start < timeout:
            line = self._proc.stdout.readline()
            if not line:
                break
            try:
                resp = json.loads(line.strip())
                if resp.get("id") == self._request_id:
                    if "error" in resp:
                        log.warning("← MCP error #%d %s: %s", self._request_id, tool_name, resp["error"])
                        return {"error": resp["error"]}
                    result = resp.get("result", {})
                    content = result.get("content", [{}])
                    if isinstance(content, list) and content:
                        text_val = content[0].get("text", "{}")
                        parsed = json.loads(text_val) if text_val.startswith("{") else {"raw": text_val}
                        log.debug("← MCP response #%d %s: %s", self._request_id, tool_name, json.dumps(parsed)[:500])
                        return parsed
                    log.debug("← MCP response #%d %s: %s", self._request_id, tool_name, json.dumps(result)[:500])
                    return result
            except (json.JSONDecodeError, KeyError):
                continue
        log.warning("← MCP timeout #%d %s (%.1fs)", self._request_id, tool_name, timeout)
        return {"error": "timeout"}

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


_client: RobinhoodMCPClient | None = None


def _get_client(config: dict | None = None) -> RobinhoodMCPClient:
    global _client
    if _client is None or (_client._proc and _client._proc.poll() is not None):
        _client = RobinhoodMCPClient(config)
        _client.start()
    return _client


def add_to_watchlist(
    symbol: str,
    watchlist_name: str = "Phoenix Paper",
    config: dict | None = None,
) -> dict[str, Any]:
    """Add a ticker to a Robinhood watchlist via the MCP server."""
    client = _get_client(config)
    return client.call("add_to_watchlist", {"symbols": [symbol], "watchlist_name": watchlist_name})


def get_watchlists(config: dict | None = None) -> dict[str, Any]:
    """List available Robinhood watchlists via the MCP server."""
    client = _get_client(config)
    return client.call("get_watchlists", {})
