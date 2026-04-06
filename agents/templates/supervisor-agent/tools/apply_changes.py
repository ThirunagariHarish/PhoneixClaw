"""Apply (stage) approved improvements via Phoenix API.

Stages improvements as `pending_improvements` on each agent — they only take
effect when the user approves them via the dashboard.

Usage:
    python apply_changes.py --input results.json --stage --output applied.json
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
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


def stage_improvements(test_results: dict) -> dict:
    """Stage passing proposals as pending_improvements on each agent."""
    api = _api_config()
    summary = {
        "staged_at": datetime.now(timezone.utc).isoformat(),
        "agents_updated": 0,
        "total_staged": 0,
        "details": [],
    }

    if not api["url"]:
        summary["error"] = "no API URL configured"
        return summary

    try:
        import httpx
        headers = {"X-Agent-Key": api["key"]} if api["key"] else {}

        for agent_block in test_results.get("results", []):
            agent_id = agent_block.get("agent_id")
            if not agent_id:
                continue

            passing = [
                tp for tp in agent_block.get("tested_proposals", [])
                if tp.get("passes")
            ]
            if not passing:
                continue

            staged_items = [
                {
                    "id": str(uuid.uuid4()),
                    "type": p["proposal"].get("type"),
                    "current": p["proposal"].get("current"),
                    "proposed": p["proposal"].get("proposed"),
                    "reason": p["proposal"].get("reason"),
                    "expected_impact": p["proposal"].get("expected_impact"),
                    "test_results": {
                        "win_rate_delta": p.get("win_rate_delta"),
                        "sharpe_delta": p.get("sharpe_delta"),
                        "confidence": p.get("confidence"),
                    },
                    "staged_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending_approval",
                }
                for p in passing
            ]

            try:
                resp = httpx.put(
                    f"{api['url']}/api/v2/agents/{agent_id}/pending-improvements",
                    headers=headers,
                    json={"improvements": staged_items},
                    timeout=15,
                )
                if resp.status_code in (200, 201):
                    summary["agents_updated"] += 1
                    summary["total_staged"] += len(staged_items)
                    summary["details"].append({
                        "agent_id": agent_id,
                        "agent_name": agent_block.get("agent_name", ""),
                        "staged": len(staged_items),
                    })
                else:
                    summary["details"].append({
                        "agent_id": agent_id,
                        "error": f"HTTP {resp.status_code}",
                    })
            except Exception as e:
                summary["details"].append({
                    "agent_id": agent_id,
                    "error": str(e)[:200],
                })

    except Exception as e:
        summary["error"] = str(e)[:200]

    return summary


def main():
    parser = argparse.ArgumentParser(description="Apply staged improvements")
    parser.add_argument("--input", required=True)
    parser.add_argument("--stage", action="store_true", help="Stage improvements (always required for safety)")
    parser.add_argument("--output", default="applied.json")
    args = parser.parse_args()

    if not args.stage:
        print("Refusing to apply directly. Use --stage to stage as pending_improvements.")
        return

    test_results = json.loads(Path(args.input).read_text())
    summary = stage_improvements(test_results)
    Path(args.output).write_text(json.dumps(summary, indent=2, default=str))
    print(f"Staged {summary['total_staged']} improvements across {summary['agents_updated']} agents")


if __name__ == "__main__":
    main()
