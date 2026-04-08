"""Nightly Consolidation tool — trigger and inspect consolidation runs via Phoenix API.

Used by the live-trader-v1 agent to kick off or monitor the "Agent Sleep"
knowledge consolidation pipeline.

Usage:
    result = await trigger_consolidation(config, run_type="manual")
    status = await get_consolidation_status(config, run_id=result["id"])
    runs = await get_recent_consolidation_runs(config, limit=5)
"""

from __future__ import annotations

import logging

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
