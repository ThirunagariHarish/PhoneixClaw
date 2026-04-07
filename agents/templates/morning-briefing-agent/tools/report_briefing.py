"""Phase 4: Persist briefing to history + dispatch to all channels.

Calls the Phoenix API so the FastAPI app handles DB writes + routing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--briefing", required=True)
    p.add_argument("--events", required=True)
    args = p.parse_args()

    briefing_path = Path(args.briefing)
    events_path = Path(args.events)
    if not briefing_path.exists():
        print(f"[report] {briefing_path} missing", file=sys.stderr)
        sys.exit(1)

    body = briefing_path.read_text()
    events = json.loads(events_path.read_text()) if events_path.exists() else {}

    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key, "Content-Type": "application/json"}
        payload = {
            "kind": "morning",
            "title": "Phoenix Morning Briefing",
            "body": body,
            "data": {
                "overnight_moves": events.get("overnight_moves", {}),
                "n_messages": len(events.get("discord_messages", [])),
                "agents_at_risk": len(events.get("agent_positions", [])),
            },
            "dispatched_to": ["whatsapp", "telegram", "ws", "db"],
        }
        r = httpx.post(f"{base}/api/v2/briefings", headers=headers,
                       json=payload, timeout=15)
        if r.status_code in (200, 201):
            print(f"[report] persisted briefing id={r.json().get('id')}")
        else:
            print(f"[report] persist returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
    except Exception as exc:
        print(f"[report] persist failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
