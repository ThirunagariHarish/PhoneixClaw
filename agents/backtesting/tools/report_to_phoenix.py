"""Report progress and events to the Phoenix API.

Used by all backtesting and live agent tools to communicate status back to
the central dashboard via HTTP callbacks.

Usage (from other tools):
    from report_to_phoenix import report_progress
    report_progress("transform", "Transformed 1200 trades", 30, {"trades": 1200})

Usage (CLI, invoked by .claude/settings.json hooks):
    python tools/report_to_phoenix.py --event session_start
    python tools/report_to_phoenix.py --event session_stop
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path


def _load_config() -> dict:
    for candidate in [Path("config.json"), Path("../config.json")]:
        if candidate.exists():
            with open(candidate) as f:
                return json.load(f)

    api_url = os.environ.get("PHOENIX_API_URL", "")
    agent_id = os.environ.get("PHOENIX_AGENT_ID", "")
    api_key = os.environ.get("PHOENIX_API_KEY", "")
    if api_url and agent_id:
        return {
            "phoenix_api_url": api_url,
            "phoenix_api_key": api_key,
            "agent_id": agent_id,
        }

    return {}


def _do_http_post(url: str, payload: dict, headers: dict, timeout: int = 5):
    """Fire-and-forget HTTP POST (runs in a daemon thread)."""
    try:
        import httpx
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            print(f"[report_to_phoenix] HTTP {resp.status_code}: {resp.text[:200]}")
    except ImportError:
        import urllib.request
        import urllib.error
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.URLError as e:
            print(f"[report_to_phoenix] URLError: {e}")
    except Exception as e:
        print(f"[report_to_phoenix] Error: {e}")


def report_progress(
    step: str,
    message: str,
    progress_pct: int,
    metrics: dict | None = None,
    status: str | None = None,
    config: dict | None = None,
    blocking: bool = False,
):
    """Report backtesting or live agent progress to the Phoenix API.

    By default runs in a background daemon thread so the caller never blocks
    on network I/O.  Pass blocking=True for CLI / shutdown paths.
    """
    if config is None:
        config = _load_config()

    api_url = config.get("phoenix_api_url", "")
    api_key = config.get("phoenix_api_key", "")
    agent_id = config.get("agent_id", "")

    if not api_url or not agent_id:
        print(f"[report_to_phoenix] skip: no api_url or agent_id in config ({step}: {message})")
        return

    payload = {
        "step": step,
        "message": message,
        "progress_pct": progress_pct,
        "metrics": metrics or {},
    }
    if status:
        payload["status"] = status

    url = f"{api_url}/api/v2/agents/{agent_id}/backtest-progress"
    headers = {"X-Agent-Key": api_key}

    if blocking:
        _do_http_post(url, payload, headers)
    else:
        t = threading.Thread(target=_do_http_post, args=(url, payload, headers), daemon=True)
        t.start()


def report_heartbeat(config: dict | None = None):
    """Send a heartbeat to the Phoenix API (non-blocking)."""
    if config is None:
        config = _load_config()

    api_url = config.get("phoenix_api_url", "")
    api_key = config.get("phoenix_api_key", "")
    agent_id = config.get("agent_id", "")

    if not api_url or not agent_id:
        return

    url = f"{api_url}/api/v2/agents/{agent_id}/heartbeat"
    payload = {"status": "alive"}
    headers = {"X-Agent-Key": api_key}

    t = threading.Thread(target=_do_http_post, args=(url, payload, headers), daemon=True)
    t.start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default="heartbeat", help="Event type: session_start, session_stop, heartbeat")
    parser.add_argument("--step", default="", help="Pipeline step name")
    parser.add_argument("--message", default="", help="Progress message")
    parser.add_argument("--progress", type=int, default=0, help="Progress percentage")
    args = parser.parse_args()

    config = _load_config()

    if args.event == "session_start":
        report_progress("session", "Claude Code session started", 0, config=config)
    elif args.event == "session_stop":
        report_progress("session", "Claude Code session ended", 0, config=config)
    elif args.event == "heartbeat":
        report_heartbeat(config)
    elif args.step:
        report_progress(args.step, args.message, args.progress, config=config)
    else:
        report_heartbeat(config)


if __name__ == "__main__":
    main()
