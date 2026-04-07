"""Lightweight report helper copied from live-trader-v1 — minimal stub.

Emits progress / completion events to the Phoenix API so the dashboard
knows this one-shot agent is alive and then finished.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def report_progress(step: str, message: str, progress_pct: int = -1,
                    data: dict | None = None) -> None:
    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        agent_id = os.environ.get("PHOENIX_AGENT_ID", "")
        if not agent_id:
            return
        httpx.post(
            f"{base}/api/v2/agents/{agent_id}/backtest-progress",
            headers={"X-Agent-Key": key, "Content-Type": "application/json"},
            json={"step": step, "message": message, "progress_pct": progress_pct,
                  "data": data or {}},
            timeout=10,
        )
    except Exception:
        pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--event", required=True)
    p.add_argument("--status", default="success")
    p.add_argument("--data", default="{}")
    args = p.parse_args()
    try:
        data = json.loads(args.data)
    except Exception:
        data = {}
    report_progress(args.event, f"{args.event}: {args.status}", -1, data)
    print(json.dumps({"event": args.event, "status": args.status}))


if __name__ == "__main__":
    main()
