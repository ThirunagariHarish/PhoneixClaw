"""Token budget endpoints — per-agent and system-wide.

Phase H7. The dashboard uses these to show:
- System-wide spend dashboard ("$23.40 of $100 daily budget used")
- Per-agent budget cards on the agent detail page
- A "Set budget" form on agent settings
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.src.deps import DbSession

router = APIRouter(prefix="/api/v2/budget", tags=["budget"])


class BudgetUpdate(BaseModel):
    daily_token_budget_usd: float | None = None
    monthly_token_budget_usd: float | None = None


@router.get("/system")
async def system_budget():
    """Return system-wide budget usage across all agents."""
    try:
        from apps.api.src.services.budget_enforcer import get_system_usage_summary
        return await get_system_usage_summary()
    except Exception as exc:
        return {"error": str(exc)[:200]}


@router.get("/agents/{agent_id}")
async def agent_budget(agent_id: str):
    """Return current budget status for a specific agent."""
    try:
        from apps.api.src.services.budget_enforcer import check_budget
        return await check_budget(uuid.UUID(agent_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


@router.put("/agents/{agent_id}")
async def update_agent_budget(agent_id: str, payload: BudgetUpdate, session: DbSession):
    """Update an agent's daily/monthly token budget."""
    from sqlalchemy import select
    from datetime import datetime, timezone
    from shared.db.models.agent import Agent

    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if payload.daily_token_budget_usd is not None:
        agent.daily_token_budget_usd = payload.daily_token_budget_usd
    if payload.monthly_token_budget_usd is not None:
        agent.monthly_token_budget_usd = payload.monthly_token_budget_usd
    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return {
        "agent_id": agent_id,
        "daily_token_budget_usd": agent.daily_token_budget_usd,
        "monthly_token_budget_usd": agent.monthly_token_budget_usd,
    }


@router.post("/agents/{agent_id}/reset-pause")
async def reset_auto_pause(agent_id: str, session: DbSession):
    """Clear auto_paused_reason so a budget-paused agent can run again.

    Use this after raising the agent's budget or after a budget reset.
    """
    from sqlalchemy import select
    from datetime import datetime, timezone
    from shared.db.models.agent import Agent

    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    previous = agent.auto_paused_reason
    agent.auto_paused_reason = None
    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return {"agent_id": agent_id, "cleared": previous}
