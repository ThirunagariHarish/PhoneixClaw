"""Phase 5: Persist EOD brief to briefing_history and dispatch."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--brief", required=True)
    p.add_argument("--trades", required=True)
    p.add_argument("--missed", required=True)
    args = p.parse_args()

    body = Path(args.brief).read_text()
    trades = json.loads(Path(args.trades).read_text()) if Path(args.trades).exists() else {}
    missed = json.loads(Path(args.missed).read_text()) if Path(args.missed).exists() else {}

    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key, "Content-Type": "application/json"}
        payload = {
            "kind": "eod",
            "title": f"Phoenix EOD Analysis — {trades.get('date', '')}",
            "body": body,
            "data": {
                "total_trades": trades.get("total_trades", 0),
                "total_pnl": trades.get("total_pnl", 0),
                "win_rate": trades.get("win_rate", 0),
                "missed_count": missed.get("missed_count", 0),
                "per_agent": trades.get("per_agent", [])[:10],
            },
            "agents_woken": len(trades.get("per_agent") or []),
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
