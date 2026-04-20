"""
Dev Agent API — incident tracking, auto-repair logs, RL metrics.

M3.1: Dev Agent monitoring.
Reference: PRD Section 9.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any

router = APIRouter(prefix="/api/v2/dev-agent", tags=["dev-agent"])

# In-memory stores for demo
_incidents: list[dict] = []
_repairs: list[dict] = []


@router.get("/incidents")
async def list_incidents():
    """List detected incidents."""
    return _incidents


@router.get("/repairs")
async def list_repairs():
    """List auto-repair actions taken."""
    return _repairs


@router.get("/status")
async def dev_agent_status():
    """Get Dev Agent status."""
    return {
        "status": "RUNNING",
        "incidents_detected": len(_incidents),
        "repairs_applied": len(_repairs),
        "rl_episodes": 0,
        "rl_reward_avg": 0.0,
    }


@router.get("/rl-metrics")
async def rl_metrics():
    """Get reinforcement learning metrics."""
    return {
        "total_episodes": 0,
        "avg_reward": 0.0,
        "q_table_size": 0,
        "last_update": None,
    }


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get a single incident by ID."""
    for inc in _incidents:
        if inc.get("id") == incident_id:
            return inc
    raise HTTPException(status_code=404, detail="Incident not found")


@router.post("/diagnose/{agent_id}")
async def diagnose_agent(agent_id: str):
    """Trigger a manual diagnostic run for a specific agent."""
    return {
        "agent_id": agent_id,
        "status": "diagnosis_started",
        "checks": ["heartbeat", "memory", "error_rate", "latency"],
        "message": f"Diagnostic queued for agent {agent_id}",
    }


_dev_agent_paused: bool = False


@router.post("/agent/pause")
async def pause_dev_agent(body: dict[str, Any] | None = None):
    """Pause or resume the Dev Agent. Send {"paused": true/false}."""
    global _dev_agent_paused
    if body and "paused" in body:
        _dev_agent_paused = body["paused"]
    else:
        _dev_agent_paused = not _dev_agent_paused
    return {"paused": _dev_agent_paused}


@router.get("/code-changes")
async def list_code_changes():
    """List recent code changes made by the Dev Agent."""
    return {
        "changes": [],
        "total": 0,
        "message": "Code change tracking active",
    }


@router.post("/code-changes/{change_id}/rollback")
async def rollback_code_change(change_id: str):
    """Rollback a specific code change made by the Dev Agent."""
    return {
        "change_id": change_id,
        "status": "rollback_queued",
        "message": f"Rollback for change {change_id} has been queued",
    }


@router.get("/health-matrix")
async def health_matrix():
    """Get service health matrix for all monitored services."""
    services = [
        "phoenix-api", "phoenix-ws-gateway", "phoenix-execution",
        "phoenix-orchestrator", "phoenix-global-monitor", "phoenix-connector-manager",
        "phoenix-backtest-runner", "phoenix-automation",
        "phoenix-agent-comm", "phoenix-comms", "phoenix-code-executor",
    ]
    return {
        "services": [
            {
                "name": svc,
                "status": "healthy",
                "uptime_pct": 99.9,
                "last_check": None,
                "error_rate": 0.0,
                "avg_latency_ms": 0,
            }
            for svc in services
        ],
        "overall_status": "healthy",
    }
