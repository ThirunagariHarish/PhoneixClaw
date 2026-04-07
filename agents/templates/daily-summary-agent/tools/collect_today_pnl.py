"""Phase 1: Collect today's PnL grouped by agent.

Pulls from the Phoenix API instead of querying the DB directly so this tool
can run inside any Claude Code session that has network access.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="today_pnl.json")
    args = p.parse_args()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    iso = today_start.isoformat()

    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key} if key else {}

        r = httpx.get(f"{base}/api/v2/agents", headers=headers, timeout=15)
        agents = r.json() if r.status_code == 200 else []
        if not isinstance(agents, list):
            agents = []
    except Exception as exc:
        print(f"[collect] agents fetch failed: {exc}", file=sys.stderr)
        agents = []

    per_agent: list[dict] = []
    total_pnl = 0.0
    total_trades = 0

    for agent in agents:
        agent_id = agent.get("id")
        name = agent.get("name", "unknown")
        if not agent_id:
            continue
        try:
            r = httpx.get(
                f"{base}/api/v2/agents/{agent_id}/live-trades?since={iso}",
                headers=headers, timeout=15,
            )
            trades = r.json() if r.status_code == 200 else []
            if not isinstance(trades, list):
                trades = []
        except Exception:
            trades = []

        count = len(trades)
        pnl = sum(float(t.get("pnl_dollar") or 0) for t in trades)
        if count == 0 and pnl == 0:
            continue
        per_agent.append({
            "agent_id": agent_id,
            "name": name,
            "count": count,
            "pnl": round(pnl, 2),
        })
        total_pnl += pnl
        total_trades += count

    per_agent.sort(key=lambda a: a["pnl"], reverse=True)

    result = {
        "date": today_start.strftime("%Y-%m-%d"),
        "trades": per_agent,
        "total_pnl": round(total_pnl, 2),
        "total_trades": total_trades,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"[collect] {total_trades} trades across {len(per_agent)} agents, total ${total_pnl:+.2f}")


if __name__ == "__main__":
    main()
