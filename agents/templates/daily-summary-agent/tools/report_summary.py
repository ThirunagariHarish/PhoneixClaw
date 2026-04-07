"""Phase 3: Persist to briefing_history + dispatch via notification_dispatcher.

Single POST to /api/v2/briefings — the backend handles both the DB insert
and the fan-out to WhatsApp/Telegram/WebSocket/DB.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--summary", required=True)
    p.add_argument("--data", required=True)
    args = p.parse_args()

    summary_text = Path(args.summary).read_text()
    data = json.loads(Path(args.data).read_text()) if Path(args.data).exists() else {}

    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key, "Content-Type": "application/json"}

        payload = {
            "kind": "daily_summary",
            "title": f"Phoenix Daily Summary — {data.get('date', '')}",
            "body": summary_text,
            "data": {
                "total_pnl": data.get("total_pnl", 0),
                "total_trades": data.get("total_trades", 0),
                "agents_reported": len(data.get("trades") or []),
            },
            "agents_woken": len(data.get("trades") or []),
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
