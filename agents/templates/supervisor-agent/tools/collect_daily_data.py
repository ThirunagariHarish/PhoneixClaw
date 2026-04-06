"""Collect today's trading data from all agents via Phoenix API.

Usage:
    python collect_daily_data.py --config config.json --output daily_data.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _api_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            return {
                "url": cfg.get("phoenix_api_url") or os.getenv("PHOENIX_API_URL", ""),
                "key": cfg.get("phoenix_api_key", ""),
            }
        except Exception:
            pass
    return {"url": os.getenv("PHOENIX_API_URL", ""), "key": ""}


def collect() -> dict:
    """Collect today's trade data across all agents."""
    api = _api_config()
    if not api["url"]:
        return {"error": "no API URL configured"}

    result = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "agents": [],
        "total_trades": 0,
        "total_paper_trades": 0,
        "total_watchlist": 0,
    }

    try:
        import httpx
        headers = {"X-Agent-Key": api["key"]} if api["key"] else {}

        # Get all agents
        agents_resp = httpx.get(f"{api['url']}/api/v2/agents", headers=headers, timeout=15)
        if agents_resp.status_code != 200:
            return {"error": f"agents fetch HTTP {agents_resp.status_code}"}

        agents = agents_resp.json()
        if not isinstance(agents, list):
            agents = agents.get("agents", [])

        for agent in agents:
            agent_id = agent.get("id")
            if not agent_id:
                continue

            agent_data = {
                "id": agent_id,
                "name": agent.get("name", ""),
                "status": agent.get("status", ""),
                "type": agent.get("type", ""),
                "trades": [],
                "watchlist_count": 0,
                "paper_count": 0,
            }

            # Get today's trades
            try:
                tr_resp = httpx.get(
                    f"{api['url']}/api/v2/trades/today",
                    headers=headers, timeout=15,
                )
                if tr_resp.status_code == 200:
                    today_trades = tr_resp.json()
                    if isinstance(today_trades, list):
                        agent_trades = [t for t in today_trades if t.get("agent_id") == agent_id]
                        agent_data["trades"] = agent_trades
                        result["total_trades"] += len(agent_trades)
            except Exception as e:
                agent_data["trades_error"] = str(e)[:100]

            # Get paper portfolio
            try:
                pp_resp = httpx.get(
                    f"{api['url']}/api/v2/agents/{agent_id}/paper-portfolio",
                    headers=headers, timeout=15,
                )
                if pp_resp.status_code == 200:
                    paper = pp_resp.json()
                    agent_data["paper_count"] = paper.get("open_positions", 0) + paper.get("closed_positions", 0)
                    agent_data["paper_realized_pnl"] = paper.get("total_realized_pnl", 0)
                    agent_data["paper_unrealized_pnl"] = paper.get("total_unrealized_pnl", 0)
                    result["total_paper_trades"] += agent_data["paper_count"]
            except Exception as e:
                agent_data["paper_error"] = str(e)[:100]

            result["agents"].append(agent_data)

    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    parser = argparse.ArgumentParser(description="Collect daily trading data")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="daily_data.json")
    args = parser.parse_args()

    result = collect()
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"Collected data for {len(result.get('agents', []))} agents → {args.output}")
    print(f"  Total trades: {result.get('total_trades', 0)}")
    print(f"  Total paper trades: {result.get('total_paper_trades', 0)}")


if __name__ == "__main__":
    main()
