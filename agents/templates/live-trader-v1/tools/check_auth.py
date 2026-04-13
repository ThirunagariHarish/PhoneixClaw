"""Verify broker gateway authentication status.

The agent calls this at startup and periodically to ensure the broker
session is alive.  Talks to the broker gateway HTTP API instead of
spawning a local MCP subprocess.

Usage:
    python3 tools/check_auth.py --config config.json

Output (stdout): JSON with session status.
"""
from __future__ import annotations

import json
import sys


def main():
    config_path = "config.json"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--config" and i < len(sys.argv) - 1:
            config_path = sys.argv[i + 1]

    try:
        with open(config_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {}

    broker_url = config.get("broker_gateway_url", "http://localhost:8040")
    account_id = config.get("broker_account_id", "")

    try:
        import httpx

        params = {"account_id": account_id} if account_id else {}
        resp = httpx.get(f"{broker_url}/auth/status", params=params, timeout=10.0)
        result = resp.json()
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"authenticated": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
