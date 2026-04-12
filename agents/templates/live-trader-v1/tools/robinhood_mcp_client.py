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
            env["RH_USERNAME"] = creds.get("username", "")
            env["RH_PASSWORD"] = creds.get("password", "")
            env["RH_TOTP_SECRET"] = creds.get("totp_secret", "")
        if self._config.get("paper_mode"):
            env["PAPER_MODE"] = "true"
        if "HOME" not in env or not env["HOME"]:
            env["HOME"] = str(Path.cwd())
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
                        return {"error": resp["error"]}
                    result = resp.get("result", {})
                    content = result.get("content", [{}])
                    if isinstance(content, list) and content:
                        text_val = content[0].get("text", "{}")
                        return json.loads(text_val) if text_val.startswith("{") else {"raw": text_val}
                    return result
            except (json.JSONDecodeError, KeyError):
                continue
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
