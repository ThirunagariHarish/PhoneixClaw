"""Phase 3: Wake every eligible child agent by publishing a cron trigger.

Reuses the shared Redis trigger bus from shared/triggers/bus.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


async def _main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--events", required=True)
    args = p.parse_args()

    events_path = Path(args.events)
    if not events_path.exists():
        print(f"[wake] {events_path} missing", file=sys.stderr)
        return

    events = json.loads(events_path.read_text())

    # Import the trigger bus lazily so this script can run inside an agent workdir
    # where PYTHONPATH may not include the repo root.
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    try:
        from shared.triggers import get_bus, Trigger, TriggerType
    except Exception as exc:
        print(f"[wake] trigger bus unavailable: {exc}", file=sys.stderr)
        return

    # Query eligible agents via the Phoenix API
    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key} if key else {}
        r = httpx.get(f"{base}/api/v2/agents", headers=headers, timeout=10)
        agents = r.json() if r.status_code == 200 else []
    except Exception as exc:
        print(f"[wake] agents list fetch failed: {exc}", file=sys.stderr)
        agents = []

    WAKE_ELIGIBLE = {"BACKTEST_COMPLETE", "APPROVED", "PAPER", "RUNNING", "PAUSED"}
    eligible = [a for a in agents if a.get("status") in WAKE_ELIGIBLE]

    bus = get_bus()
    sent = 0
    for agent in eligible:
        try:
            await bus.publish(Trigger(
                agent_id=str(agent["id"]),
                type=TriggerType.MORNING_BRIEFING,
                payload={
                    "overnight_events": {
                        k: v for k, v in events.items()
                        if k in ("overnight_moves", "discord_messages", "collected_at")
                    },
                },
            ))
            sent += 1
        except Exception as exc:
            print(f"[wake] publish failed for {agent.get('name')}: {exc}", file=sys.stderr)

    print(json.dumps({
        "eligible": len(eligible),
        "triggers_sent": sent,
        "skipped": len(agents) - len(eligible),
    }))


if __name__ == "__main__":
    asyncio.run(_main())
