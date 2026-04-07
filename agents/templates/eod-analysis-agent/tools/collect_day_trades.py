"""Phase 1: Collect today's trades across all live/paper agents."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="day_trades.json")
    args = p.parse_args()

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    iso = today_start.isoformat()

    import httpx
    base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
    key = os.environ.get("PHOENIX_API_KEY", "")
    headers = {"X-Agent-Key": key} if key else {}

    # Fetch all agents
    try:
        r = httpx.get(f"{base}/api/v2/agents", headers=headers, timeout=15)
        agents = r.json() if r.status_code == 200 else []
        if not isinstance(agents, list):
            agents = []
    except Exception as exc:
        print(f"[collect] agents fetch failed: {exc}", file=sys.stderr)
        agents = []

    per_agent: list[dict] = []
    total_trades = 0
    total_pnl = 0.0
    total_winners = 0
    total_losers = 0

    for agent in agents:
        if agent.get("status") not in ("RUNNING", "PAPER", "APPROVED"):
            continue
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

        if not trades:
            continue

        winners = [t for t in trades if float(t.get("pnl_dollar") or 0) > 0]
        losers = [t for t in trades if float(t.get("pnl_dollar") or 0) < 0]
        realized = sum(float(t.get("pnl_dollar") or 0) for t in trades)
        best = max(trades, key=lambda t: float(t.get("pnl_dollar") or 0)) if trades else None
        worst = min(trades, key=lambda t: float(t.get("pnl_dollar") or 0)) if trades else None

        per_agent.append({
            "agent_id": agent_id,
            "name": name,
            "character": agent.get("character"),
            "count": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "pnl": round(realized, 2),
            "avg_win": round(sum(float(t.get("pnl_dollar") or 0) for t in winners) / len(winners), 2) if winners else 0.0,
            "avg_loss": round(sum(float(t.get("pnl_dollar") or 0) for t in losers) / len(losers), 2) if losers else 0.0,
            "best": {
                "symbol": (best or {}).get("symbol"),
                "pnl": float((best or {}).get("pnl_dollar") or 0),
            } if best else None,
            "worst": {
                "symbol": (worst or {}).get("symbol"),
                "pnl": float((worst or {}).get("pnl_dollar") or 0),
            } if worst else None,
        })
        total_trades += len(trades)
        total_pnl += realized
        total_winners += len(winners)
        total_losers += len(losers)

    per_agent.sort(key=lambda a: a["pnl"], reverse=True)

    result = {
        "date": today_start.strftime("%Y-%m-%d"),
        "per_agent": per_agent,
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "total_winners": total_winners,
        "total_losers": total_losers,
        "win_rate": round(total_winners / total_trades, 4) if total_trades else 0.0,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"[collect] {total_trades} trades across {len(per_agent)} agents, "
          f"PnL ${total_pnl:+.2f}, win rate {result['win_rate']:.1%}")


if __name__ == "__main__":
    main()
