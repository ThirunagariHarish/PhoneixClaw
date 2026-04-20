"""
Daily Signals API routes: list signals, pipeline status, signal detail, analytics.

Phoenix v3 — Queries agent_trades + trade_signals + agents tables for real signal data.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent import Agent
from shared.db.models.agent_trade import AgentTrade
from shared.db.models.trade_signal import TradeSignal

router = APIRouter(prefix="/api/v2/daily-signals", tags=["daily-signals"])


class SignalResponse(BaseModel):
    id: str
    time: str
    symbol: str
    direction: str
    confidence: float
    source_agent: str
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward: float | None = None
    status: str
    reasoning: str | None = None
    pattern_matches: int | None = None
    pnl: float | None = None
    research_note: str | None = None
    technical_chart_ref: str | None = None
    risk_analysis: str | None = None


class PipelineAgentResponse(BaseModel):
    id: str
    name: str
    status: str
    last_run: str | None = None
    signals_produced: int


class PipelineStatusResponse(BaseModel):
    status: str
    instance_id: str | None = None
    agents: list[PipelineAgentResponse]
    total_signals_today: int


class DailySummaryResponse(BaseModel):
    total_signals_today: int
    win_rate_7d: float
    avg_rr: float
    active_signals: int
    pipeline_health: str


class AnalyticsResponse(BaseModel):
    win_rate_by_agent: list[dict]
    avg_return: float
    avg_rr: float
    total_signals: int


def _parse_sl_tp_from_raw(signal_raw: str | None) -> tuple[float | None, float | None]:
    """Try to extract stop_loss/take_profit from the raw signal JSON."""
    if not signal_raw:
        return None, None
    try:
        parsed = json.loads(signal_raw)
        sl = parsed.get("stop_loss") or parsed.get("sl") or parsed.get("stop")
        tp = parsed.get("take_profit") or parsed.get("tp") or parsed.get("target")
        return (float(sl) if sl is not None else None, float(tp) if tp is not None else None)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, None


def _parse_sl_tp_from_trail(decision_trail: dict | None) -> tuple[float | None, float | None]:
    """Try to extract stop_loss/take_profit from the decision trail JSON."""
    if not decision_trail or not isinstance(decision_trail, dict):
        return None, None
    sl = decision_trail.get("stop_loss") or decision_trail.get("sl")
    tp = decision_trail.get("take_profit") or decision_trail.get("tp") or decision_trail.get("target")
    try:
        return (float(sl) if sl is not None else None, float(tp) if tp is not None else None)
    except (TypeError, ValueError):
        return None, None


def _trade_to_signal(
    trade: AgentTrade,
    agent_name: str,
    ts_stop_loss: float | None = None,
    ts_take_profit: float | None = None,
    ts_rr: float | None = None,
) -> SignalResponse:
    """Map an AgentTrade row to the signal response format."""
    # Resolve stop_loss: TradeSignal > decision_trail > signal_raw > fallback
    sl = ts_stop_loss
    tp = ts_take_profit

    if sl is None or tp is None:
        trail_sl, trail_tp = _parse_sl_tp_from_trail(trade.decision_trail)
        if sl is None:
            sl = trail_sl
        if tp is None:
            tp = trail_tp

    if sl is None or tp is None:
        raw_sl, raw_tp = _parse_sl_tp_from_raw(trade.signal_raw)
        if sl is None:
            sl = raw_sl
        if tp is None:
            tp = raw_tp

    # Fallback: use exit_price as take_profit proxy if available
    if tp is None and trade.exit_price:
        tp = trade.exit_price

    # Compute risk/reward
    rr = ts_rr
    if rr is None and trade.entry_price and sl is not None and tp is not None:
        risk = abs(trade.entry_price - sl)
        reward = abs(tp - trade.entry_price)
        rr = round(reward / risk, 2) if risk > 0 else None

    # Extract research/risk notes from decision_trail if available
    research_note = None
    risk_analysis = None
    if trade.decision_trail and isinstance(trade.decision_trail, dict):
        research_note = trade.decision_trail.get("research_note") or trade.decision_trail.get("research")
        risk_analysis = trade.decision_trail.get("risk_analysis") or trade.decision_trail.get("risk_note")

    return SignalResponse(
        id=str(trade.id),
        time=trade.entry_time.isoformat() if trade.entry_time else trade.created_at.isoformat(),
        symbol=trade.ticker,
        direction=trade.side.upper() if trade.side else "UNKNOWN",
        confidence=trade.model_confidence or 0.0,
        source_agent=agent_name,
        entry_price=trade.entry_price or 0.0,
        stop_loss=sl,
        take_profit=tp,
        risk_reward=rr,
        status=trade.status.upper() if trade.status else "NEW",
        reasoning=trade.reasoning,
        pattern_matches=trade.pattern_matches,
        pnl=trade.pnl_dollar,
        research_note=research_note,
        risk_analysis=risk_analysis,
    )


async def _compute_win_rate_7d(db: AsyncSession) -> float:
    """Compute win rate from closed AgentTrades in the last 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((AgentTrade.pnl_dollar > 0, 1), else_=0)).label("wins"),
        )
        .where(AgentTrade.status.in_(["closed", "CLOSED", "filled", "FILLED"]))
        .where(AgentTrade.exit_time >= cutoff)
    )
    row = result.first()
    if not row or not row.total or row.total == 0:
        return 0.0
    wins = row.wins or 0
    return round((wins / row.total) * 100, 1)


@router.get("/summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    db: AsyncSession = Depends(get_session),
) -> DailySummaryResponse:
    """Aggregated daily summary with real win rate."""
    today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    today_end = datetime.combine(date.today(), time.max, tzinfo=timezone.utc)

    # Count today's signals
    count_result = await db.execute(
        select(func.count()).where(AgentTrade.entry_time.between(today_start, today_end))
    )
    total_today = count_result.scalar() or 0

    # Active signals
    active_result = await db.execute(
        select(func.count())
        .where(AgentTrade.entry_time.between(today_start, today_end))
        .where(AgentTrade.status.in_(["open", "OPEN", "active", "ACTIVE"]))
    )
    active = active_result.scalar() or 0

    # Win rate
    win_rate = await _compute_win_rate_7d(db)

    # Avg R:R from trade_signals
    rr_result = await db.execute(
        select(func.avg(TradeSignal.risk_reward_ratio))
        .where(TradeSignal.created_at.between(today_start, today_end))
    )
    avg_rr = rr_result.scalar() or 0.0

    # Pipeline health: check if any trading agents are running
    agent_result = await db.execute(
        select(func.count()).where(Agent.type == "trading").where(Agent.status.in_(["RUNNING", "PAPER"]))
    )
    running_count = agent_result.scalar() or 0
    health = "healthy" if running_count > 0 else "degraded"

    return DailySummaryResponse(
        total_signals_today=total_today,
        win_rate_7d=win_rate,
        avg_rr=round(float(avg_rr), 1),
        active_signals=active,
        pipeline_health=health,
    )


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    db: AsyncSession = Depends(get_session),
    days: int = Query(7, description="Number of days to look back"),
) -> AnalyticsResponse:
    """Signal performance analytics: win rate by agent, avg return, avg R:R."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Win rate by agent
    result = await db.execute(
        select(
            Agent.name,
            func.count().label("total"),
            func.sum(case((AgentTrade.pnl_dollar > 0, 1), else_=0)).label("wins"),
            func.avg(AgentTrade.pnl_pct).label("avg_return"),
        )
        .outerjoin(Agent, AgentTrade.agent_id == Agent.id)
        .where(AgentTrade.status.in_(["closed", "CLOSED", "filled", "FILLED"]))
        .where(AgentTrade.exit_time >= cutoff)
        .group_by(Agent.name)
    )
    rows = result.all()

    win_rate_by_agent = []
    total_signals = 0
    total_return_sum = 0.0
    total_count = 0

    for row in rows:
        agent_total = row.total or 0
        agent_wins = row.wins or 0
        agent_wr = round((agent_wins / agent_total) * 100, 1) if agent_total > 0 else 0.0
        agent_avg_ret = round(float(row.avg_return or 0), 2)
        win_rate_by_agent.append({
            "agent": row.name or "unknown",
            "total": agent_total,
            "wins": agent_wins,
            "win_rate": agent_wr,
            "avg_return": agent_avg_ret,
        })
        total_signals += agent_total
        total_return_sum += agent_avg_ret * agent_total
        total_count += agent_total

    overall_avg_return = round(total_return_sum / total_count, 2) if total_count > 0 else 0.0

    # Avg R:R from TradeSignal
    rr_result = await db.execute(
        select(func.avg(TradeSignal.risk_reward_ratio))
        .where(TradeSignal.created_at >= cutoff)
    )
    avg_rr = round(float(rr_result.scalar() or 0), 2)

    return AnalyticsResponse(
        win_rate_by_agent=win_rate_by_agent,
        avg_return=overall_avg_return,
        avg_rr=avg_rr,
        total_signals=total_signals,
    )


@router.get("", response_model=list[SignalResponse])
async def list_signals(
    db: AsyncSession = Depends(get_session),
    target_date: date | None = Query(None, description="Date to query (default: today)"),
) -> list[SignalResponse]:
    """List daily signals from agent trades, enriched with stop_loss/take_profit from trade_signals."""
    query_date = target_date or date.today()
    start = datetime.combine(query_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(query_date, time.max, tzinfo=timezone.utc)

    result = await db.execute(
        select(AgentTrade, Agent.name)
        .outerjoin(Agent, AgentTrade.agent_id == Agent.id)
        .where(AgentTrade.entry_time.between(start, end))
        .order_by(AgentTrade.entry_time.desc())
        .limit(100)
    )
    rows = result.all()

    # Batch fetch matching trade_signals for stop_loss/take_profit
    trade_agent_ids = [(r[0].agent_id, r[0].ticker) for r in rows]
    ts_map: dict[tuple, tuple[float | None, float | None, float | None]] = {}

    if trade_agent_ids:
        ts_result = await db.execute(
            select(
                TradeSignal.agent_id,
                TradeSignal.ticker,
                TradeSignal.stop_loss,
                TradeSignal.take_profit,
                TradeSignal.risk_reward_ratio,
            )
            .where(TradeSignal.created_at.between(start, end))
            .order_by(TradeSignal.created_at.desc())
        )
        for ts_row in ts_result.all():
            key = (ts_row.agent_id, ts_row.ticker)
            if key not in ts_map:
                ts_map[key] = (ts_row.stop_loss, ts_row.take_profit, ts_row.risk_reward_ratio)

    signals = []
    for trade, name in rows:
        key = (trade.agent_id, trade.ticker)
        ts_sl, ts_tp, ts_rr = ts_map.get(key, (None, None, None))
        signals.append(_trade_to_signal(trade, name or "unknown", ts_sl, ts_tp, ts_rr))

    return signals


@router.get("/pipeline", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    db: AsyncSession = Depends(get_session),
) -> PipelineStatusResponse:
    """Get active trading agents and their signal counts for today."""
    today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)

    # Get agents with today's trade counts
    result = await db.execute(
        select(
            Agent.id, Agent.name, Agent.status, Agent.last_trade_at,
            func.count(AgentTrade.id).label("trade_count"),
        )
        .outerjoin(AgentTrade, (AgentTrade.agent_id == Agent.id) & (AgentTrade.entry_time >= today_start))
        .where(Agent.type == "trading")
        .group_by(Agent.id, Agent.name, Agent.status, Agent.last_trade_at)
    )
    rows = result.all()

    agents = []
    total = 0
    for row in rows:
        count = row.trade_count or 0
        total += count
        agents.append(PipelineAgentResponse(
            id=str(row.id),
            name=row.name,
            status=row.status,
            last_run=row.last_trade_at.isoformat() if row.last_trade_at else None,
            signals_produced=count,
        ))

    pipeline_status = "deployed" if any(a.status in ("RUNNING", "PAPER") for a in agents) else "not_deployed"
    return PipelineStatusResponse(status=pipeline_status, instance_id=None, agents=agents, total_signals_today=total)


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal_detail(
    signal_id: str,
    db: AsyncSession = Depends(get_session),
) -> SignalResponse:
    """Get signal detail by trade ID."""
    try:
        trade_uuid = uuid.UUID(signal_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signal ID")

    result = await db.execute(
        select(AgentTrade, Agent.name)
        .outerjoin(Agent, AgentTrade.agent_id == Agent.id)
        .where(AgentTrade.id == trade_uuid)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")

    trade, agent_name = row

    # Try to get SL/TP from trade_signal
    ts_result = await db.execute(
        select(TradeSignal.stop_loss, TradeSignal.take_profit, TradeSignal.risk_reward_ratio)
        .where(TradeSignal.agent_id == trade.agent_id)
        .where(TradeSignal.ticker == trade.ticker)
        .order_by(TradeSignal.created_at.desc())
        .limit(1)
    )
    ts_row = ts_result.first()
    ts_sl = ts_row.stop_loss if ts_row else None
    ts_tp = ts_row.take_profit if ts_row else None
    ts_rr = ts_row.risk_reward_ratio if ts_row else None

    return _trade_to_signal(trade, agent_name or "unknown", ts_sl, ts_tp, ts_rr)
