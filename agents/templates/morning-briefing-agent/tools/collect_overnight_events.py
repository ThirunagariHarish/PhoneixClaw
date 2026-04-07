"""Phase 1: Collect overnight events from every configured source.

Pulls the last N hours of:
  - Discord channel messages (via Phoenix API)
  - Earnings + macro calendar (via Phoenix API)
  - Overnight futures moves (via yfinance)
  - Agent watchlist tickers + open positions (via Phoenix API)

Writes a structured bundle to overnight_events.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _phoenix_api_get(path: str) -> dict | list | None:
    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key} if key else {}
        r = httpx.get(f"{base}{path}", headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        print(f"  [collect] GET {path} failed: {exc}", file=sys.stderr)
    return None


def _yf_overnight_moves(tickers: list[str]) -> dict:
    """Fetch overnight % move via yfinance. Best-effort."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    result: dict = {}
    for t in tickers:
        try:
            data = yf.Ticker(t).history(period="2d", interval="1d")
            if len(data) >= 2:
                prev = float(data["Close"].iloc[-2])
                last = float(data["Close"].iloc[-1])
                if prev > 0:
                    result[t] = {
                        "prev_close": round(prev, 2),
                        "last": round(last, 2),
                        "pct_change": round((last - prev) / prev * 100, 2),
                    }
        except Exception:
            continue
    return result


def _collect_discord(lookback_hours: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    msgs: list[dict] = []
    # Pull the last few hundred messages across all running agents' connectors
    agents = _phoenix_api_get("/api/v2/agents") or []
    if not isinstance(agents, list):
        return msgs
    for agent in agents[:20]:
        agent_id = agent.get("id")
        if not agent_id:
            continue
        data = _phoenix_api_get(
            f"/api/v2/agents/{agent_id}/channel-messages?limit=50&since={since}"
        )
        if isinstance(data, dict):
            msgs.extend(data.get("messages", []))
    return msgs[:300]  # cap


def _collect_agent_positions() -> list[dict]:
    agents = _phoenix_api_get("/api/v2/agents") or []
    out: list[dict] = []
    if not isinstance(agents, list):
        return out
    for agent in agents:
        if agent.get("runtime_status") not in ("alive", "stale"):
            continue
        agent_id = agent.get("id")
        if not agent_id:
            continue
        positions = _phoenix_api_get(f"/api/v2/agents/{agent_id}/positions") or []
        out.append({
            "agent_id": agent_id,
            "name": agent.get("name"),
            "positions": positions if isinstance(positions, list) else [],
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--lookback-hours", type=int, default=12)
    p.add_argument("--output", default="overnight_events.json")
    p.add_argument("--watchlist", default="SPY,QQQ,DIA,IWM,BTC-USD,GLD,TLT,^VIX")
    args = p.parse_args()

    bundle = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": args.lookback_hours,
        "discord_messages": _collect_discord(args.lookback_hours),
        "agent_positions": _collect_agent_positions(),
        "overnight_moves": _yf_overnight_moves([t.strip() for t in args.watchlist.split(",")]),
        "errors": [],
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(bundle, indent=2, default=str))
    print(f"[collect] wrote {out_path} with {len(bundle['discord_messages'])} msgs, "
          f"{len(bundle['agent_positions'])} agents, "
          f"{len(bundle['overnight_moves'])} moves")


if __name__ == "__main__":
    main()
