"""
Nightly Consolidation API routes.

Endpoints:
  POST /api/v2/agents/{agent_id}/consolidation/run          — trigger manual run (202)
  GET  /api/v2/agents/{agent_id}/consolidation/runs         ?limit=10 — list recent runs
  GET  /api/v2/agents/{agent_id}/consolidation/runs/{run_id} — get specific run
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from apps.api.src.deps import DbSession
from apps.api.src.repositories.consolidation_repo import ConsolidationRepository
from apps.api.src.services.consolidation_service import ConsolidationService
from shared.db.models.agent import Agent
from shared.db.models.consolidation import ConsolidationRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/agents", tags=["consolidation"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TriggerConsolidationRequest(BaseModel):
    run_type: str = "manual"  # nightly | weekly | manual


class ConsolidationRunResponse(BaseModel):
    id: str
    agent_id: str
    run_type: str
    status: str
    scheduled_for: str | None
    started_at: str | None
    completed_at: str | None
    trades_analyzed: int
    wiki_entries_written: int
    wiki_entries_updated: int
    wiki_entries_pruned: int
    patterns_found: int
    rules_proposed: int
    consolidation_report: str | None
    error_message: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_run(run: ConsolidationRun) -> ConsolidationRunResponse:
    return ConsolidationRunResponse(
        id=str(run.id),
        agent_id=str(run.agent_id),
        run_type=run.run_type,
        status=run.status,
        scheduled_for=run.scheduled_for.isoformat() if run.scheduled_for else None,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        trades_analyzed=run.trades_analyzed,
        wiki_entries_written=run.wiki_entries_written,
        wiki_entries_updated=run.wiki_entries_updated,
        wiki_entries_pruned=run.wiki_entries_pruned,
        patterns_found=run.patterns_found,
        rules_proposed=run.rules_proposed,
        consolidation_report=run.consolidation_report,
        error_message=run.error_message,
        created_at=run.created_at.isoformat() if run.created_at else "",
    )


async def _get_agent_and_verify(agent_id: str, request: Request, session) -> Agent:
    """Fetch the agent and enforce IDOR ownership check."""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id format")

    agent = await session.get(Agent, agent_uuid)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    requesting_user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)

    if not is_admin and str(agent.user_id) != str(requesting_user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return agent


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/consolidation/run",
    response_model=ConsolidationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_consolidation_run(
    agent_id: str,
    request: Request,
    session: DbSession,
    body: TriggerConsolidationRequest = TriggerConsolidationRequest(),
) -> ConsolidationRunResponse:
    """Trigger a manual consolidation run.  Returns 202 immediately; run executes in background."""
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = ConsolidationRepository(session)

    run = await repo.create_run(agent_id=agent.id, run_type=body.run_type)
    await session.commit()
    await session.refresh(run)

    run_id = run.id
    agent_uuid = agent.id

    # Fire-and-forget background task
    async def _run_bg() -> None:
        from shared.db.engine import get_session

        async for bg_session in get_session():
            try:
                svc = ConsolidationService(bg_session)
                await svc.run_consolidation(agent_id=agent_uuid, run_id=run_id, run_type=body.run_type)
            except Exception:
                logger.exception("[consolidation] background run failed: run_id=%s", run_id)
            finally:
                break

    asyncio.create_task(_run_bg())
    logger.info(
        "[consolidation] triggered run_id=%s agent_id=%s run_type=%s",
        run_id,
        agent_uuid,
        body.run_type,
    )
    return _serialize_run(run)


@router.get(
    "/{agent_id}/consolidation/runs",
    response_model=list[ConsolidationRunResponse],
)
async def list_consolidation_runs(
    agent_id: str,
    request: Request,
    session: DbSession,
    limit: int = Query(10, ge=1, le=50),
) -> list[ConsolidationRunResponse]:
    """Return the most recent consolidation runs for an agent (newest first)."""
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = ConsolidationRepository(session)
    runs = await repo.list_for_agent(agent_id=agent.id, limit=limit)
    return [_serialize_run(r) for r in runs]


@router.get(
    "/{agent_id}/consolidation/runs/{run_id}",
    response_model=ConsolidationRunResponse,
)
async def get_consolidation_run(
    agent_id: str,
    run_id: str,
    request: Request,
    session: DbSession,
) -> ConsolidationRunResponse:
    """Return a specific consolidation run."""
    agent = await _get_agent_and_verify(agent_id, request, session)

    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_id format")

    repo = ConsolidationRepository(session)
    run = await repo.get_by_id(run_uuid)
    if not run or str(run.agent_id) != str(agent.id):
        raise HTTPException(status_code=404, detail="Consolidation run not found")

    return _serialize_run(run)
