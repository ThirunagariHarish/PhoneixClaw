"""Token usage tracking and budget monitoring service."""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select, func

from shared.db.engine import get_session
from shared.db.models.token_usage import TokenUsage

MODEL_COSTS_PER_1K = {
    "claude-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-sonnet": {"input": 0.003, "output": 0.015},
    "claude-opus": {"input": 0.015, "output": 0.075},
}

DEFAULT_MONTHLY_BUDGET_USD = 100.0

TASK_MODEL_ROUTING = {
    "orchestration": "claude-haiku",
    "progress_parsing": "claude-haiku",
    "tool_selection": "claude-haiku",
    "error_handling": "claude-sonnet",
    "code_generation": "claude-sonnet",
    "user_chat": "claude-sonnet",
    "complex_analysis": "claude-sonnet",
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_COSTS_PER_1K.get(model, MODEL_COSTS_PER_1K["claude-sonnet"])
    return (input_tokens / 1000 * rates["input"]) + (output_tokens / 1000 * rates["output"])


def get_recommended_model(task_type: str) -> str:
    return TASK_MODEL_ROUTING.get(task_type, "claude-haiku")


async def get_usage_summary(monthly_budget_usd: float = DEFAULT_MONTHLY_BUDGET_USD) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    async with get_session() as session:
        async def _agg(since: date) -> dict:
            stmt = select(
                func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input"),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output"),
                func.coalesce(func.sum(TokenUsage.estimated_cost_usd), 0.0).label("cost"),
            ).where(TokenUsage.date >= since)
            row = (await session.execute(stmt)).one()
            total = int(row.input) + int(row.output)
            return {"total_tokens": total, "input_tokens": int(row.input), "output_tokens": int(row.output), "estimated_cost_usd": float(row.cost)}

        daily = await _agg(today)
        weekly = await _agg(week_start)
        monthly = await _agg(month_start)

        used_pct = (monthly["estimated_cost_usd"] / monthly_budget_usd * 100) if monthly_budget_usd > 0 else 0
        remaining = max(0.0, monthly_budget_usd - monthly["estimated_cost_usd"])

        by_agent_stmt = (
            select(
                TokenUsage.agent_id,
                func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0).label("tokens_today"),
                func.coalesce(func.sum(TokenUsage.estimated_cost_usd), 0.0).label("cost_today"),
            )
            .where(TokenUsage.date >= today)
            .group_by(TokenUsage.agent_id)
            .order_by(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens).desc())
            .limit(10)
        )
        agent_rows = (await session.execute(by_agent_stmt)).all()

        by_model_stmt = (
            select(
                TokenUsage.model,
                func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0).label("tokens"),
                func.coalesce(func.sum(TokenUsage.estimated_cost_usd), 0.0).label("cost"),
            )
            .where(TokenUsage.date >= month_start)
            .group_by(TokenUsage.model)
            .order_by(func.sum(TokenUsage.estimated_cost_usd).desc())
        )
        model_rows = (await session.execute(by_model_stmt)).all()

    return {
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "budget": {
            "monthly_limit_usd": monthly_budget_usd,
            "used_pct": round(used_pct, 1),
            "remaining_usd": round(remaining, 2),
        },
        "by_agent": [
            {"agent_id": str(r.agent_id) if r.agent_id else None, "tokens_today": int(r.tokens_today), "cost_today_usd": float(r.cost_today)}
            for r in agent_rows
        ],
        "by_model": [
            {"model": r.model, "tokens": int(r.tokens), "cost_usd": float(r.cost)}
            for r in model_rows
        ],
    }


async def get_usage_history(days: int = 30) -> list[dict]:
    since = date.today() - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(
                TokenUsage.date,
                func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input"),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output"),
                func.coalesce(func.sum(TokenUsage.estimated_cost_usd), 0.0).label("cost"),
            )
            .where(TokenUsage.date >= since)
            .group_by(TokenUsage.date)
            .order_by(TokenUsage.date)
        )
        rows = (await session.execute(stmt)).all()

    return [
        {
            "date": str(r.date),
            "input_tokens": int(r.input),
            "output_tokens": int(r.output),
            "total_tokens": int(r.input) + int(r.output),
            "estimated_cost_usd": float(r.cost),
        }
        for r in rows
    ]


async def record_usage(
    instance_id: UUID | None,
    agent_id: UUID | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    cost = estimate_cost(model, input_tokens, output_tokens)
    async with get_session() as session:
        usage = TokenUsage(
            instance_id=instance_id,
            agent_id=agent_id,
            date=date.today(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
        )
        session.add(usage)
        await session.commit()
