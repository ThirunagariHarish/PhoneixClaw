"""
Performance API routes: portfolio, agents, instruments, risk.

Aggregates real data from AgentTrade, AgentMetric, and Position tables.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent import Agent
from shared.db.models.agent_metric import AgentMetric
from shared.db.models.agent_trade import AgentTrade

router = APIRouter(prefix="/api/v2/performance", tags=["performance"])


def _period_to_delta(period: str) -> timedelta:
    mapping = {"1d": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}
    return mapping.get(period, timedelta(days=7))


@router.get("/portfolio")
async def get_portfolio_performance(
    period: str = Query("7d", pattern="^(1d|7d|30d|90d)$"),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.now(timezone.utc) - _period_to_delta(period)

    total_pnl_q = await session.execute(
        select(func.coalesce(func.sum(AgentTrade.pnl_dollar), 0.0)).where(
            AgentTrade.entry_time >= since
        )
    )
    total_pnl = float(total_pnl_q.scalar() or 0)

    trade_count_q = await session.execute(
        select(func.count(AgentTrade.id)).where(AgentTrade.entry_time >= since)
    )
    trade_count = int(trade_count_q.scalar() or 0)

    daily_q = await session.execute(
        select(
            func.date_trunc("day", AgentTrade.entry_time).label("day"),
            func.sum(AgentTrade.pnl_dollar).label("daily_pnl"),
        )
        .where(AgentTrade.entry_time >= since)
        .group_by("day")
        .order_by("day")
    )
    daily_rows = daily_q.all()

    running_total = 0.0
    equity_curve = []
    timestamps = []
    for row in daily_rows:
        running_total += float(row.daily_pnl or 0)
        equity_curve.append(round(running_total, 2))
        timestamps.append(row.day.strftime("%Y-%m-%d") if row.day else "")

    return {
        "total_value": round(running_total, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": 0.0,
        "period": period,
        "trade_count": trade_count,
        "equity_curve": equity_curve,
        "timestamps": timestamps,
    }


@router.get("/agents")
async def get_agents_performance(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    q = await session.execute(
        select(
            AgentTrade.agent_id,
            func.count(AgentTrade.id).label("trades_count"),
            func.sum(AgentTrade.pnl_dollar).label("total_pnl"),
            func.avg(
                case((AgentTrade.pnl_dollar > 0, 1.0), else_=0.0)
            ).label("win_rate"),
        )
        .group_by(AgentTrade.agent_id)
        .order_by(func.sum(AgentTrade.pnl_dollar).desc())
        .limit(limit)
    )
    rows = q.all()

    agents = []
    for row in rows:
        agent_q = await session.execute(select(Agent.name).where(Agent.id == row.agent_id))
        name = agent_q.scalar() or str(row.agent_id)
        agents.append({
            "id": str(row.agent_id),
            "name": name,
            "pnl": round(float(row.total_pnl or 0), 2),
            "win_rate": round(float(row.win_rate or 0), 4),
            "trades_count": int(row.trades_count or 0),
        })

    return {"agents": agents}


@router.get("/instruments")
async def get_instruments_performance(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    q = await session.execute(
        select(
            AgentTrade.ticker,
            func.count(AgentTrade.id).label("trades_count"),
            func.sum(AgentTrade.pnl_dollar).label("total_pnl"),
        )
        .group_by(AgentTrade.ticker)
        .order_by(func.sum(AgentTrade.pnl_dollar).desc())
        .limit(limit)
    )
    rows = q.all()

    return {
        "instruments": [
            {
                "symbol": row.ticker,
                "pnl": round(float(row.total_pnl or 0), 2),
                "trades_count": int(row.trades_count or 0),
            }
            for row in rows
        ]
    }


@router.get("/summary")
async def get_performance_summary(
    session: AsyncSession = Depends(get_session),
):
    total_q = await session.execute(
        select(
            func.count(AgentTrade.id).label("total"),
            func.sum(AgentTrade.pnl_dollar).label("total_pnl"),
            func.avg(AgentTrade.pnl_dollar).label("avg_pnl"),
            func.max(AgentTrade.pnl_dollar).label("best"),
            func.min(AgentTrade.pnl_dollar).label("worst"),
            func.sum(case((AgentTrade.pnl_dollar > 0, 1), else_=0)).label("wins"),
            func.sum(case((AgentTrade.pnl_dollar <= 0, 1), else_=0)).label("losses"),
            func.sum(case((AgentTrade.pnl_dollar > 0, AgentTrade.pnl_dollar), else_=0.0)).label("gross_profit"),
            func.sum(
                case(
                    (AgentTrade.pnl_dollar < 0, cast(func.abs(AgentTrade.pnl_dollar), Float)),
                    else_=0.0,
                )
            ).label("gross_loss"),
        )
    )
    row = total_q.one()

    total_trades = int(row.total or 0)
    wins = int(row.wins or 0)
    losses = int(row.losses or 0)
    total_pnl = float(row.total_pnl or 0)
    gross_profit = float(row.gross_profit or 0)
    gross_loss = float(row.gross_loss or 0)

    return {
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": 0.0,
        "win_rate": round(wins / max(total_trades, 1), 4),
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "avg_trade_pnl": round(float(row.avg_pnl or 0), 2),
        "best_trade": round(float(row.best or 0), 2),
        "worst_trade": round(float(row.worst or 0), 2),
        "profit_factor": round(gross_profit / max(gross_loss, 0.01), 2),
    }


@router.get("/risk")
async def get_risk_metrics(
    period: str = Query("7d", pattern="^(1d|7d|30d)$"),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.now(timezone.utc) - _period_to_delta(period)

    trades_q = await session.execute(
        select(AgentTrade.pnl_dollar)
        .where(AgentTrade.entry_time >= since, AgentTrade.pnl_dollar.isnot(None))
        .order_by(AgentTrade.entry_time)
    )
    pnl_values = [float(r[0]) for r in trades_q.all()]

    if not pnl_values:
        return {"var_95": 0, "var_99": 0, "max_drawdown": 0, "max_drawdown_pct": 0, "exposure_pct": 0, "period": period}

    import numpy as np
    arr = np.array(pnl_values)
    var_95 = round(float(np.percentile(arr, 5)), 2)
    var_99 = round(float(np.percentile(arr, 1)), 2)

    cumsum = np.cumsum(arr)
    peak = np.maximum.accumulate(cumsum)
    drawdown = cumsum - peak
    max_dd = round(float(drawdown.min()), 2)

    return {
        "var_95": var_95,
        "var_99": var_99,
        "max_drawdown": max_dd,
        "max_drawdown_pct": 0.0,
        "exposure_pct": 0.0,
        "period": period,
    }
