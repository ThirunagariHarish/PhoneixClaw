"""Nightly Consolidation tool — trigger and inspect consolidation runs via Phoenix API.

Used by the live-trader-v1 agent to kick off or monitor the "Agent Sleep"
knowledge consolidation pipeline.

Usage (CLI):
    python tools/nightly_consolidation.py [--dry-run]

Usage (library):
    result = await trigger_consolidation(config, run_type="manual")
    status = await get_consolidation_status(config, run_id=result["id"])
    runs = await get_recent_consolidation_runs(config, limit=5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


async def trigger_consolidation(config: dict, run_type: str = "manual") -> dict:
    """Trigger nightly consolidation via Phoenix API.

    Args:
        config: Agent config dict with keys:
            - phoenix_api_url: Base URL of Phoenix API (e.g. http://localhost:8011)
            - agent_id: UUID of the agent
            - phoenix_api_key: Bearer token for auth
        run_type: One of 'nightly', 'weekly', 'manual'.  Defaults to 'manual'.

    Returns:
        ConsolidationRun dict from the API (status will be 'pending').
    """
    url = f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/consolidation/run"
    headers = {"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"}
    payload = {"run_type": run_type}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "[consolidation] triggered run_id=%s run_type=%s agent=%s",
            result.get("id"),
            run_type,
            config.get("agent_id"),
        )
        return result


async def get_consolidation_status(config: dict, run_id: str) -> dict:
    """Get status of a specific consolidation run.

    Args:
        config: Agent config dict (phoenix_api_url, agent_id, phoenix_api_key).
        run_id: UUID of the consolidation run.

    Returns:
        ConsolidationRun dict with current status, stats, and report.
    """
    url = (
        f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}"
        f"/consolidation/runs/{run_id}"
    )
    headers = {"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def get_recent_consolidation_runs(config: dict, limit: int = 5) -> list[dict]:
    """Get recent consolidation runs for the agent.

    Args:
        config: Agent config dict (phoenix_api_url, agent_id, phoenix_api_key).
        limit: Maximum number of runs to return (1–50).

    Returns:
        List of ConsolidationRun dicts, newest first.
    """
    url = f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/consolidation/runs"
    headers = {"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"}
    params = {"limit": limit}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_POLL_INTERVAL_SECONDS = 10
_MAX_POLL_SECONDS = 600  # 10 minutes


def _load_config() -> dict:
    """Read config.json from the current working directory (agent root)."""
    config_path = Path("config.json")
    if not config_path.exists():
        # Fall back to the directory where this script lives
        config_path = Path(__file__).parent.parent / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            "config.json not found. Run this script from the agent directory."
        )
    with config_path.open() as fh:
        return json.load(fh)


async def _cli_main(dry_run: bool) -> int:
    """Main async CLI routine.  Returns exit code: 0=success, 2=failure."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        config = _load_config()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    agent_id = config.get("agent_id")
    api_url = config.get("phoenix_api_url", "http://localhost:8011")
    if not agent_id:
        print("ERROR: config.json missing 'agent_id'", file=sys.stderr)
        return 2

    if dry_run:
        print(
            f"[dry-run] Would POST /api/v2/agents/{agent_id}/consolidation/run  (api={api_url})"
        )
        return 0

    # Step 1 — trigger
    print(f"Triggering nightly consolidation for agent {agent_id} …")
    try:
        run = await trigger_consolidation(config, run_type="nightly")
    except Exception as exc:
        print(f"ERROR: Could not trigger consolidation: {exc}", file=sys.stderr)
        return 2

    run_id: str = run["id"]
    print(f"Run started: {run_id}  (status={run['status']})")

    # Step 2 — poll until completed | failed | timeout
    deadline = time.monotonic() + _MAX_POLL_SECONDS
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        try:
            status_data = await get_consolidation_status(config, run_id=run_id)
        except Exception as exc:
            print(f"WARN: Poll error (will retry): {exc}", file=sys.stderr)
            if time.monotonic() >= deadline:
                print("ERROR: Timeout waiting for consolidation to complete.", file=sys.stderr)
                return 2
            continue

        current_status = status_data.get("status", "unknown")
        print(f"  … status={current_status}")

        if current_status == "completed":
            # Step 3 — print report
            report = status_data.get("consolidation_report") or "(no report)"
            print("\n" + "=" * 60)
            print(report)
            print("=" * 60)
            trades = status_data.get("trades_analyzed", 0)
            patterns = status_data.get("patterns_found", 0)
            written = status_data.get("wiki_entries_written", 0)
            updated = status_data.get("wiki_entries_updated", 0)
            pruned = status_data.get("wiki_entries_pruned", 0)
            rules = status_data.get("rules_proposed", 0)
            print(
                f"\nSummary: {trades} trades · {patterns} patterns · "
                f"{written} written · {updated} updated · {pruned} pruned · {rules} rules"
            )
            return 0

        if current_status == "failed":
            error = status_data.get("error_message") or "unknown error"
            print(f"ERROR: Consolidation run failed: {error}", file=sys.stderr)
            return 2

        if time.monotonic() >= deadline:
            print(
                f"ERROR: Timed out after {_MAX_POLL_SECONDS}s — run still in status={current_status}",
                file=sys.stderr,
            )
            return 2


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Trigger Phoenix nightly consolidation for this agent."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without actually running.",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(_cli_main(dry_run=args.dry_run))
    sys.exit(exit_code)
