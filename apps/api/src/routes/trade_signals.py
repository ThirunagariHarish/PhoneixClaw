"""Trade signal logging API — called by live agents for every decision.

The live-trader's decision_engine.py logs every decision (executed, rejected,
watchlist, paper) here with a feature snapshot. At EOD, the scheduler enriches
these rows with actual outcome prices and feeds them back into training.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from apps.api.src.deps import DbSession
from shared.db.models.trade_signal import TradeSignal

router = APIRouter(prefix="/api/v2/trade-signals", tags=["trade-signals"])


class TradeSignalCreate(BaseModel):
    agent_id: str
    ticker: str
    direction: str | None = None
    signal_source: str = "discord"
    source_message_id: str | None = None
    predicted_prob: float | None = None
    model_confidence: float | None = None
    decision: str = Field(..., pattern="^(executed|rejected|watchlist|paper)$")
    rejection_reason: str | None = None
    features: dict = Field(default_factory=dict)


@router.post("", status_code=status.HTTP_201_CREATED)
async def log_signal(payload: TradeSignalCreate, session: DbSession):
    """Log a trade signal decision (called by decision_engine.py in live agents)."""
    try:
        agent_uuid = uuid.UUID(payload.agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    signal = TradeSignal(
        id=uuid.uuid4(),
        agent_id=agent_uuid,
        ticker=payload.ticker.upper(),
        direction=payload.direction,
        signal_source=payload.signal_source,
        source_message_id=payload.source_message_id,
        predicted_prob=payload.predicted_prob,
        model_confidence=payload.model_confidence,
        decision=payload.decision,
        rejection_reason=payload.rejection_reason,
        features=payload.features,
    )
    session.add(signal)
    await session.commit()
    return {"id": str(signal.id), "logged": True}


@router.get("")
async def list_signals(
    session: DbSession,
    agent_id: str | None = None,
    decision: str | None = None,
    missed_only: bool = False,
    days: int = 30,
    limit: int = Query(100, ge=1, le=1000),
):
    """List trade signals with filters."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(TradeSignal).where(TradeSignal.created_at >= cutoff)
    if agent_id:
        try:
            q = q.where(TradeSignal.agent_id == uuid.UUID(agent_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent_id")
    if decision:
        q = q.where(TradeSignal.decision == decision)
    if missed_only:
        q = q.where(TradeSignal.was_missed_opportunity.is_(True))

    q = q.order_by(desc(TradeSignal.created_at)).limit(limit)
    result = await session.execute(q)
    signals = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "agent_id": str(s.agent_id),
            "ticker": s.ticker,
            "direction": s.direction,
            "decision": s.decision,
            "predicted_prob": s.predicted_prob,
            "model_confidence": s.model_confidence,
            "rejection_reason": s.rejection_reason,
            "realized_pnl_pct": s.realized_pnl_pct,
            "was_missed_opportunity": s.was_missed_opportunity,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "evaluated_at": s.evaluated_at.isoformat() if s.evaluated_at else None,
        }
        for s in signals
    ]


@router.get("/stats")
async def signal_stats(session: DbSession, agent_id: str | None = None, days: int = 30):
    """Aggregate stats: total decisions, breakdown, missed opportunities."""
    from datetime import timedelta

    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(
        TradeSignal.decision,
        func.count(TradeSignal.id).label("count"),
        func.sum(func.cast(TradeSignal.was_missed_opportunity, type_=sa.Integer)).label("missed"),
    ).where(TradeSignal.created_at >= cutoff).group_by(TradeSignal.decision)

    if agent_id:
        try:
            q = q.where(TradeSignal.agent_id == uuid.UUID(agent_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent_id")

    try:
        import sqlalchemy as sa  # noqa
        result = await session.execute(q)
        rows = result.all()
    except Exception:
        # Simpler fallback without casting
        q2 = select(
            TradeSignal.decision,
            func.count(TradeSignal.id).label("count"),
        ).where(TradeSignal.created_at >= cutoff).group_by(TradeSignal.decision)
        if agent_id:
            q2 = q2.where(TradeSignal.agent_id == uuid.UUID(agent_id))
        result = await session.execute(q2)
        rows = [(r.decision, r.count, 0) for r in result.all()]

    breakdown = {}
    total_missed = 0
    for row in rows:
        if hasattr(row, "decision"):
            breakdown[row.decision] = {"count": row.count, "missed": getattr(row, "missed", 0) or 0}
            total_missed += getattr(row, "missed", 0) or 0
        else:
            breakdown[row[0]] = {"count": row[1], "missed": row[2] or 0}
            total_missed += row[2] or 0

    return {
        "days": days,
        "breakdown": breakdown,
        "total_missed_opportunities": total_missed,
    }
