"""
Prediction Markets — Agent health & activity endpoints (Phase 15.6).

GET  /api/v2/pm/agents/health    — heartbeat status (reads Redis pm:agent:*:heartbeat)
GET  /api/v2/pm/agents/activity  — last 100 activity log entries (PMAgentActivityLog)
POST /api/v2/pm/agents/cycle     — manually trigger one agent cycle (TopBetsAgent.run_cycle)

Health status logic:
  - heartbeat key exists in Redis  → "healthy"
  - key missing, last activity <10 min ago  → "degraded"
  - otherwise  → "dead"

Reference: docs/architecture/polymarket-phase15.md §8 Phase 15.6, §10 Redis Keys
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import PMAgentActivityLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pm/agents", tags=["pm-agents"])

# Redis keys that map to agent names — must stay in sync with §10
_AGENT_HEARTBEAT_KEYS: dict[str, str] = {
    "top_bets": "pm:agent:top_bets:heartbeat",
    "sum_to_one_arb": "pm:agent:sum_to_one_arb:heartbeat",
    "cross_venue_arb": "pm:agent:cross_venue_arb:heartbeat",
}

_DEGRADED_WINDOW_MINUTES = 10


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AgentStatus(BaseModel):
    status: str  # healthy | degraded | dead
    last_seen: str | None
    ttl_remaining: int | None  # seconds, or None if not in Redis


class AgentHealthResponse(BaseModel):
    agents: dict[str, AgentStatus]
    overall: str  # healthy | degraded | dead


class ActivityLogEntry(BaseModel):
    id: str
    agent_type: str
    severity: str
    action: str
    detail: dict | None
    markets_scanned_today: int | None
    bets_generated_today: int | None
    created_at: str


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return str(user_id)


# ---------------------------------------------------------------------------
# Redis helper
# ---------------------------------------------------------------------------


async def _get_redis_client():
    """Return an aioredis client or None if Redis is not available."""
    try:
        import os

        import redis.asyncio as aioredis  # type: ignore[import]

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        return aioredis.from_url(url, decode_responses=True)
    except Exception as exc:
        logger.debug("Redis unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health", response_model=AgentHealthResponse)
async def get_agent_health(
    request: Request,
    db: DbSession,
) -> AgentHealthResponse:
    """Report liveness status for all known PM agents."""
    _require_user(request)

    redis = await _get_redis_client()

    # Fetch last activity per agent_type for degraded-check fallback
    last_activity_by_agent: dict[str, datetime] = {}
    try:
        res = await db.execute(
            select(PMAgentActivityLog)
            .order_by(PMAgentActivityLog.created_at.desc())
            .limit(200)
        )
        for entry in res.scalars().all():
            if entry.agent_type not in last_activity_by_agent:
                last_activity_by_agent[entry.agent_type] = entry.created_at
    except Exception as exc:
        logger.warning("pm.agents.health: DB query failed: %s", exc)

    agent_statuses: dict[str, AgentStatus] = {}
    now = datetime.now(timezone.utc)

    for agent_name, hb_key in _AGENT_HEARTBEAT_KEYS.items():
        hb_value: str | None = None
        ttl: int | None = None

        if redis:
            try:
                hb_value = await redis.get(hb_key)
                ttl_raw = await redis.ttl(hb_key)
                ttl = int(ttl_raw) if ttl_raw and ttl_raw > 0 else None
            except Exception as exc:
                logger.debug("Redis get failed for %s: %s", hb_key, exc)

        if hb_value is not None:
            agent_statuses[agent_name] = AgentStatus(
                status="healthy",
                last_seen=hb_value,
                ttl_remaining=ttl,
            )
            continue

        # Key missing — check last activity timestamp
        last_seen = last_activity_by_agent.get(agent_name)
        if last_seen:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            age_minutes = (now - last_seen).total_seconds() / 60
            if age_minutes < _DEGRADED_WINDOW_MINUTES:
                agent_statuses[agent_name] = AgentStatus(
                    status="degraded",
                    last_seen=last_seen.isoformat(),
                    ttl_remaining=None,
                )
                continue

        agent_statuses[agent_name] = AgentStatus(
            status="dead",
            last_seen=last_activity_by_agent[agent_name].isoformat() if agent_name in last_activity_by_agent else None,
            ttl_remaining=None,
        )

    if redis:
        try:
            await redis.aclose()
        except Exception:
            pass

    # Compute overall status
    statuses = [s.status for s in agent_statuses.values()]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "dead" for s in statuses):
        overall = "dead"
    else:
        overall = "degraded"

    return AgentHealthResponse(agents=agent_statuses, overall=overall)


@router.get("/activity", response_model=list[ActivityLogEntry])
async def get_activity_log(
    request: Request,
    db: DbSession,
) -> list[ActivityLogEntry]:
    """Return the last 100 PM agent activity log entries."""
    _require_user(request)

    result = await db.execute(
        select(PMAgentActivityLog)
        .order_by(PMAgentActivityLog.created_at.desc())
        .limit(100)
    )
    entries = result.scalars().all()

    return [
        ActivityLogEntry(
            id=str(e.id),
            agent_type=e.agent_type,
            severity=e.severity,
            action=e.action,
            detail=e.detail,
            markets_scanned_today=e.markets_scanned_today,
            bets_generated_today=e.bets_generated_today,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in entries
    ]


@router.post("/cycle", status_code=status.HTTP_202_ACCEPTED)
async def trigger_cycle(
    request: Request,
    db: DbSession,
) -> dict:
    """Manually trigger one TopBetsAgent cycle (non-blocking, best-effort)."""
    _require_user(request)

    try:
        import asyncio

        from agents.polymarket.top_bets.agent import TopBetsAgent  # type: ignore[import]

        agent = TopBetsAgent()
        asyncio.ensure_future(agent.run_cycle())
        return {"triggered": True, "message": "TopBetsAgent cycle scheduled"}
    except Exception as exc:
        logger.warning("pm.agents.cycle trigger failed: %s", exc)
        return {"triggered": False, "message": str(exc)}
