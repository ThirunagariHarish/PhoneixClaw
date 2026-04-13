"""Proxy agent lifecycle operations to phoenix-agent-orchestrator service."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

ORCHESTRATOR_URL = os.environ.get("AGENT_ORCHESTRATOR_URL", "http://phoenix-agent-orchestrator:8070")
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=30.0)
    return _client


async def start_agent(agent_id: str, config: dict | None = None) -> dict:
    """Start an agent via the orchestrator service."""
    try:
        resp = await _get_client().post(f"/agents/{agent_id}/start", json=config or {})
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("Orchestrator start_agent failed for %s: %s", agent_id, exc)
        raise


async def stop_agent(agent_id: str) -> dict:
    """Stop an agent via the orchestrator service."""
    try:
        resp = await _get_client().post(f"/agents/{agent_id}/stop")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("Orchestrator stop_agent failed for %s: %s", agent_id, exc)
        raise


async def resume_agent(agent_id: str) -> dict:
    """Resume an agent via the orchestrator service."""
    try:
        resp = await _get_client().post(f"/agents/{agent_id}/resume")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("Orchestrator resume_agent failed for %s: %s", agent_id, exc)
        raise


async def get_agent_status(agent_id: str) -> dict:
    """Get agent status from orchestrator."""
    try:
        resp = await _get_client().get(f"/agents/{agent_id}/status")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Orchestrator status check failed for %s: %s", agent_id, exc)
        return {"status": "unknown", "error": str(exc)}
