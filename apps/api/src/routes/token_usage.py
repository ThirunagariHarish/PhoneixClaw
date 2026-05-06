"""Token usage monitoring API routes."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from apps.api.src.deps import DbSession
from shared.db.models.token_usage import TokenUsage

router = APIRouter(prefix="/api/v2/token-usage", tags=["token-usage"])

PRICING = {
    "claude-haiku": {"input_per_1m": 0.25, "output_per_1m": 1.25},
    "claude-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
}


@router.get("")
async def get_token_usage(session: DbSession):
    """Aggregate token usage: daily, weekly, monthly, by agent, by model."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    async def _sum_range(since: date):
        result = await session.execute(
            select(
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                func.coalesce(func.sum(TokenUsage.estimated_cost_usd), 0.0),
            ).where(TokenUsage.date >= since)
        )
        row = result.one()
        return {
            "input_tokens": row[0],
            "output_tokens": row[1],
            "total_tokens": row[0] + row[1],
            "estimated_cost_usd": round(row[2], 4),
        }

    daily = await _sum_range(today)
    weekly = await _sum_range(week_ago)
    monthly = await _sum_range(month_ago)

    # By agent
    agent_result = await session.execute(
        select(
            TokenUsage.agent_id,
            func.sum(TokenUsage.input_tokens),
            func.sum(TokenUsage.output_tokens),
            func.sum(TokenUsage.estimated_cost_usd),
        )
        .where(TokenUsage.date >= today)
        .group_by(TokenUsage.agent_id)
    )
    by_agent = [
        {
            "agent_id": str(row[0]) if row[0] else None,
            "tokens_today": (row[1] or 0) + (row[2] or 0),
            "cost_today_usd": round(row[3] or 0, 4),
        }
        for row in agent_result.all()
    ]

    # By model
    model_result = await session.execute(
        select(
            TokenUsage.model,
            func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens),
            func.sum(TokenUsage.estimated_cost_usd),
        )
        .where(TokenUsage.date >= month_ago)
        .group_by(TokenUsage.model)
    )
    by_model = {
        row[0]: {"tokens": row[1] or 0, "cost": round(row[2] or 0, 4)}
        for row in model_result.all()
    }

    budget_limit = 20.0  # $20/month default
    used_pct = (monthly["estimated_cost_usd"] / budget_limit * 100) if budget_limit > 0 else 0

    return {
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "budget": {
            "monthly_limit_usd": budget_limit,
            "used_pct": round(used_pct, 1),
            "remaining_usd": round(budget_limit - monthly["estimated_cost_usd"], 2),
        },
        "by_agent": by_agent,
        "by_model": by_model,
    }


@router.get("/history")
async def get_token_usage_history(
    session: DbSession,
    days: int = Query(30, ge=1, le=365),
):
    """Daily token usage over time for charts."""
    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(
            TokenUsage.date,
            func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens),
            func.sum(TokenUsage.estimated_cost_usd),
        )
        .where(TokenUsage.date >= since)
        .group_by(TokenUsage.date)
        .order_by(TokenUsage.date)
    )
    return [
        {"date": str(row[0]), "tokens": row[1] or 0, "cost_usd": round(row[2] or 0, 4)}
        for row in result.all()
    ]


class TokenUsageReport(BaseModel):
    instance_id: str | None = None
    agent_id: str | None = None
    model: str = "claude-sonnet"
    input_tokens: int = 0
    output_tokens: int = 0


@router.get("/model-routing")
async def get_model_routing():
    """Return recommended model for each task type (for token optimization)."""
    from apps.api.src.services.token_tracker import MODEL_COSTS_PER_1K, TASK_MODEL_ROUTING
    return {
        "routing": TASK_MODEL_ROUTING,
        "model_costs_per_1k": MODEL_COSTS_PER_1K,
        "default_model": "claude-haiku",
    }


@router.post("")
async def report_token_usage(payload: TokenUsageReport, session: DbSession):
    """Agent or gateway reports token consumption."""
    pricing = PRICING.get(payload.model, PRICING["claude-sonnet"])
    cost = (
        payload.input_tokens / 1_000_000 * pricing["input_per_1m"]
        + payload.output_tokens / 1_000_000 * pricing["output_per_1m"]
    )

    record = TokenUsage(
        id=uuid.uuid4(),
        instance_id=uuid.UUID(payload.instance_id) if payload.instance_id else None,
        agent_id=uuid.UUID(payload.agent_id) if payload.agent_id else None,
        date=date.today(),
        model=payload.model,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        estimated_cost_usd=round(cost, 6),
    )
    session.add(record)
    await session.commit()
    return {"recorded": True, "estimated_cost_usd": round(cost, 6)}
