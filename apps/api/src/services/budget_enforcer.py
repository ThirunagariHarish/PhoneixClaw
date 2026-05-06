"""Token budget enforcement for agents.

Phase H7: Hard cap on per-agent token spend so a runaway agent can't burn $10k.

Two enforcement points:
1. **Spawn time**: agent_gateway.create_* checks budget before launching a session.
   Returns `BUDGET_EXCEEDED` if over daily/monthly limit.
2. **Mid-session**: a heartbeat from the agent calls `record_usage()`. If the
   per-call cost would push the agent over budget, this returns False and the
   agent should self-pause (auto_paused_reason = 'budget_exceeded').

Uses `shared/pricing.py` for cost calculations.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Default per-agent budgets (used if agent.daily_token_budget_usd / monthly is NULL)
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("DEFAULT_DAILY_AGENT_BUDGET_USD", "10.0"))
DEFAULT_MONTHLY_BUDGET_USD = float(os.environ.get("DEFAULT_MONTHLY_AGENT_BUDGET_USD", "200.0"))

# System-wide hard cap (across all agents) — circuit breaker
SYSTEM_DAILY_BUDGET_USD = float(os.environ.get("SYSTEM_DAILY_BUDGET_USD", "100.0"))
SYSTEM_MONTHLY_BUDGET_USD = float(os.environ.get("SYSTEM_MONTHLY_BUDGET_USD", "2000.0"))


class BudgetExceeded(Exception):
    """Raised when an agent's token budget is exhausted."""

    def __init__(self, agent_id: str, scope: str, used: float, limit: float):
        self.agent_id = agent_id
        self.scope = scope  # 'daily' | 'monthly' | 'system_daily' | 'system_monthly'
        self.used = used
        self.limit = limit
        super().__init__(
            f"Budget exceeded for agent {agent_id}: {scope} usage ${used:.4f} >= ${limit:.4f}"
        )


async def _reset_if_new_day(agent) -> bool:
    """Reset tokens_used_today_usd if it's a new day. Returns True if reset."""
    now = datetime.now(timezone.utc)
    last_reset = agent.budget_reset_at
    if last_reset is None or last_reset.date() < now.date():
        agent.tokens_used_today_usd = 0.0
        agent.budget_reset_at = now
        if last_reset is None or last_reset.month != now.month:
            agent.tokens_used_month_usd = 0.0
        return True
    return False


async def check_budget(agent_id: uuid.UUID) -> dict:
    """Check whether an agent has budget left. Returns a status dict.

    Returns:
        {
          "ok": bool,
          "reason": str | None,
          "daily_used": float, "daily_limit": float,
          "monthly_used": float, "monthly_limit": float,
        }
    """
    from shared.db.engine import get_session
    from shared.db.models.agent import Agent

    async for db in get_session():
        agent = (await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()

        if not agent:
            return {"ok": False, "reason": "agent_not_found"}

        was_reset = await _reset_if_new_day(agent)
        if was_reset:
            await db.commit()

        daily_limit = agent.daily_token_budget_usd or DEFAULT_DAILY_BUDGET_USD
        monthly_limit = agent.monthly_token_budget_usd or DEFAULT_MONTHLY_BUDGET_USD
        daily_used = agent.tokens_used_today_usd or 0.0
        monthly_used = agent.tokens_used_month_usd or 0.0

        # Check system-wide cap first
        system_daily_used, system_monthly_used = await _get_system_usage(db)
        if system_daily_used >= SYSTEM_DAILY_BUDGET_USD:
            return {
                "ok": False, "reason": "system_daily_budget_exceeded",
                "system_daily_used": system_daily_used,
                "system_daily_limit": SYSTEM_DAILY_BUDGET_USD,
            }
        if system_monthly_used >= SYSTEM_MONTHLY_BUDGET_USD:
            return {
                "ok": False, "reason": "system_monthly_budget_exceeded",
                "system_monthly_used": system_monthly_used,
                "system_monthly_limit": SYSTEM_MONTHLY_BUDGET_USD,
            }

        if daily_used >= daily_limit:
            return {
                "ok": False, "reason": "daily_budget_exceeded",
                "daily_used": daily_used, "daily_limit": daily_limit,
                "monthly_used": monthly_used, "monthly_limit": monthly_limit,
            }
        if monthly_used >= monthly_limit:
            return {
                "ok": False, "reason": "monthly_budget_exceeded",
                "daily_used": daily_used, "daily_limit": daily_limit,
                "monthly_used": monthly_used, "monthly_limit": monthly_limit,
            }

        return {
            "ok": True, "reason": None,
            "daily_used": daily_used, "daily_limit": daily_limit,
            "monthly_used": monthly_used, "monthly_limit": monthly_limit,
            "daily_remaining": daily_limit - daily_used,
            "monthly_remaining": monthly_limit - monthly_used,
        }


async def record_usage(agent_id: uuid.UUID, model: str,
                       input_tokens: int, output_tokens: int) -> dict:
    """Record token usage for an agent and return updated budget status.

    Called from a hook in the LLM call path (or asynchronously from
    report_to_phoenix.py heartbeats).

    If the new usage pushes the agent over budget, sets auto_paused_reason.
    """
    from shared.db.engine import get_session
    from shared.db.models.agent import Agent
    from shared.pricing import calculate_cost

    cost = calculate_cost(model, input_tokens, output_tokens)
    if cost <= 0:
        return {"ok": True, "cost": 0.0, "skipped": True}

    async for db in get_session():
        agent = (await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if not agent:
            return {"ok": False, "reason": "agent_not_found"}

        await _reset_if_new_day(agent)

        agent.tokens_used_today_usd = (agent.tokens_used_today_usd or 0.0) + cost
        agent.tokens_used_month_usd = (agent.tokens_used_month_usd or 0.0) + cost

        daily_limit = agent.daily_token_budget_usd or DEFAULT_DAILY_BUDGET_USD
        monthly_limit = agent.monthly_token_budget_usd or DEFAULT_MONTHLY_BUDGET_USD

        # Auto-pause if over budget
        over_daily = agent.tokens_used_today_usd >= daily_limit
        over_monthly = agent.tokens_used_month_usd >= monthly_limit
        if (over_daily or over_monthly) and not agent.auto_paused_reason:
            agent.auto_paused_reason = (
                "daily_budget_exceeded" if over_daily else "monthly_budget_exceeded"
            )
            agent.updated_at = datetime.now(timezone.utc)
            logger.warning(
                "Agent %s auto-paused: %s (daily=$%.4f/$%.2f, monthly=$%.4f/$%.2f)",
                agent_id, agent.auto_paused_reason,
                agent.tokens_used_today_usd, daily_limit,
                agent.tokens_used_month_usd, monthly_limit,
            )

        await db.commit()

        # Update Prometheus counters (best-effort)
        try:
            from shared.metrics import LLM_COST_USD, LLM_TOKENS
            agent_type = "live"  # Caller can override via labels in future
            LLM_TOKENS.labels(agent_type=agent_type, model=model, direction="input").inc(input_tokens)
            LLM_TOKENS.labels(agent_type=agent_type, model=model, direction="output").inc(output_tokens)
            LLM_COST_USD.labels(agent_type=agent_type, model=model).inc(cost)
        except Exception:
            pass

        return {
            "ok": not (over_daily or over_monthly),
            "cost": cost,
            "daily_used": agent.tokens_used_today_usd,
            "daily_limit": daily_limit,
            "monthly_used": agent.tokens_used_month_usd,
            "monthly_limit": monthly_limit,
            "auto_paused": bool(agent.auto_paused_reason),
        }


async def _get_system_usage(db) -> tuple[float, float]:
    """Sum up system-wide daily/monthly token usage across all agents."""
    from sqlalchemy import func

    from shared.db.models.agent import Agent

    result = await db.execute(
        select(
            func.coalesce(func.sum(Agent.tokens_used_today_usd), 0.0).label("daily"),
            func.coalesce(func.sum(Agent.tokens_used_month_usd), 0.0).label("monthly"),
        )
    )
    row = result.first()
    if row:
        return float(row.daily or 0.0), float(row.monthly or 0.0)
    return 0.0, 0.0


async def get_system_usage_summary() -> dict:
    """Return system-wide usage for dashboard."""
    from shared.db.engine import get_session

    async for db in get_session():
        daily, monthly = await _get_system_usage(db)
        return {
            "daily_used_usd": round(daily, 4),
            "daily_limit_usd": SYSTEM_DAILY_BUDGET_USD,
            "daily_remaining_usd": round(SYSTEM_DAILY_BUDGET_USD - daily, 4),
            "monthly_used_usd": round(monthly, 4),
            "monthly_limit_usd": SYSTEM_MONTHLY_BUDGET_USD,
            "monthly_remaining_usd": round(SYSTEM_MONTHLY_BUDGET_USD - monthly, 4),
        }
