"""
Prediction Markets — Research endpoints (Phase 15.6 / F15-D).

POST /api/v2/pm/research/trigger  — manually trigger auto-research cycle
GET  /api/v2/pm/research/logs     — last 20 research log entries (PMStrategyResearchLog)

Reference: docs/architecture/polymarket-phase15.md §8 Phase 15.6
           docs/prd/polymarket-phase15.md F15-D (Auto-Research)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import PMStrategyResearchLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pm/research", tags=["pm-research"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ResearchLogEntry(BaseModel):
    id: str
    run_at: str
    sources_queried: dict | None
    raw_findings: str
    proposed_config_delta: dict | None
    applied: bool
    applied_at: str | None
    notes: str | None
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
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_research(
    request: Request,
    db: DbSession,
) -> dict:
    """Manually kick off one auto-research cycle (non-blocking, best-effort).

    The cycle is delegated to AutoResearchAgent which respects Redis
    ``pm:research:last_run_date`` to prevent same-day re-runs unless forced.
    """
    _require_user(request)

    try:
        import asyncio

        from agents.polymarket.top_bets.auto_research import AutoResearchAgent  # type: ignore[import]

        agent = AutoResearchAgent()
        asyncio.ensure_future(agent.run())
        return {"triggered": True, "message": "AutoResearchAgent cycle scheduled"}
    except Exception as exc:
        logger.warning("pm.research.trigger failed: %s", exc)
        return {"triggered": False, "message": str(exc)}


@router.get("/logs", response_model=list[ResearchLogEntry])
async def get_research_logs(
    request: Request,
    db: DbSession,
) -> list[ResearchLogEntry]:
    """Return the last 20 strategy research log entries."""
    _require_user(request)

    result = await db.execute(
        select(PMStrategyResearchLog)
        .order_by(PMStrategyResearchLog.run_at.desc())
        .limit(20)
    )
    entries = result.scalars().all()

    return [
        ResearchLogEntry(
            id=str(e.id),
            run_at=e.run_at.isoformat() if e.run_at else "",
            sources_queried=e.sources_queried,
            raw_findings=e.raw_findings,
            proposed_config_delta=e.proposed_config_delta,
            applied=e.applied,
            applied_at=e.applied_at.isoformat() if e.applied_at else None,
            notes=e.notes,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in entries
    ]
