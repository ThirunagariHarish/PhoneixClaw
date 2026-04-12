"""
Portfolio API routes: equity curve from trade history.

Computes daily equity values from AgentTrade P&L data.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent_trade import AgentTrade

router = APIRouter(prefix="/api/v2/portfolio", tags=["portfolio"])


@router.get("/equity-curve")
async def get_equity_curve(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Build daily equity curve from trade P&L over the given number of days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    daily_q = await session.execute(
        select(
            func.date_trunc("day", AgentTrade.entry_time).label("day"),
            func.sum(AgentTrade.pnl_dollar).label("daily_pnl"),
        )
        .where(AgentTrade.entry_time >= since, AgentTrade.pnl_dollar.isnot(None))
        .group_by("day")
        .order_by("day")
    )
    daily_rows = daily_q.all()

    if not daily_rows:
        return []

    running_total = 0.0
    curve: list[dict[str, Any]] = []
    for row in daily_rows:
        daily_pnl = float(row.daily_pnl or 0)
        running_total += daily_pnl
        prev_equity = running_total - daily_pnl
        daily_return = round(daily_pnl / max(abs(prev_equity), 1.0), 4) if prev_equity != 0 else 0.0
        curve.append({
            "date": row.day.strftime("%Y-%m-%d") if row.day else "",
            "equity": round(running_total, 2),
            "daily_return": daily_return,
        })

    return curve
