"""
Trades API routes: list trades, get trade detail, trade stats, portfolio summary.

M1.10: Trades Tab backend.
Reference: PRD Section 3.1.
"""

import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, desc, func, select

from apps.api.src.deps import DbSession
from shared.db.models.agent import Agent
from shared.db.models.agent_trade import AgentTrade
from shared.db.models.trade import TradeIntent

router = APIRouter(prefix="/api/v2/trades", tags=["trades"])


class TradeResponse(BaseModel):
    id: str
    agent_id: str
    account_id: str
    symbol: str
    side: str
    qty: float
    order_type: str
    limit_price: float | None
    stop_price: float | None
    status: str
    fill_price: float | None
    filled_at: str | None
    rejection_reason: str | None
    signal_source: str | None
    pnl_dollar: float | None
    pnl_pct: float | None
    notes: str | None
    created_at: str

    @classmethod
    def from_model(cls, t: TradeIntent) -> "TradeResponse":
        extra = t.extra_data or {}
        return cls(
            id=str(t.id),
            agent_id=str(t.agent_id),
            account_id=t.account_id,
            symbol=t.symbol,
            side=t.side,
            qty=t.qty,
            order_type=t.order_type,
            limit_price=t.limit_price,
            stop_price=t.stop_price,
            status=t.status,
            fill_price=t.fill_price,
            filled_at=t.filled_at.isoformat() if t.filled_at else None,
            rejection_reason=t.rejection_reason,
            signal_source=t.signal_source,
            pnl_dollar=extra.get("pnl_dollar"),
            pnl_pct=extra.get("pnl_pct"),
            notes=extra.get("notes"),
            created_at=t.created_at.isoformat() if t.created_at else "",
        )


@router.get("", response_model=list[TradeResponse])
async def list_trades(
    session: DbSession,
    status_filter: str | None = Query(None, alias="status"),
    symbol: str | None = None,
    agent_id: str | None = None,
    date_from: str | None = Query(None, description="ISO date string YYYY-MM-DD"),
    date_to: str | None = Query(None, description="ISO date string YYYY-MM-DD"),
    sort_by: str | None = Query(None, description="Column to sort by"),
    sort_dir: str | None = Query("desc", description="asc or desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List trade intents with optional filters."""
    query = select(TradeIntent)
    if status_filter:
        query = query.where(TradeIntent.status == status_filter)
    if symbol:
        query = query.where(TradeIntent.symbol.ilike(f"%{symbol.upper()}%"))
    if agent_id:
        query = query.where(TradeIntent.agent_id == uuid.UUID(agent_id))
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            query = query.where(TradeIntent.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            query = query.where(TradeIntent.created_at <= dt_to)
        except ValueError:
            pass

    # Sorting
    sort_column = {
        "symbol": TradeIntent.symbol,
        "side": TradeIntent.side,
        "qty": TradeIntent.qty,
        "status": TradeIntent.status,
        "fill_price": TradeIntent.fill_price,
        "created_at": TradeIntent.created_at,
    }.get(sort_by or "created_at", TradeIntent.created_at)
    if sort_dir == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    return [TradeResponse.from_model(t) for t in result.scalars().all()]


@router.get("/count")
async def trade_count(
    session: DbSession,
    status_filter: str | None = Query(None, alias="status"),
    symbol: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Return total count of trades matching filters (for pagination)."""
    query = select(func.count(TradeIntent.id))
    if status_filter:
        query = query.where(TradeIntent.status == status_filter)
    if symbol:
        query = query.where(TradeIntent.symbol.ilike(f"%{symbol.upper()}%"))
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
            query = query.where(TradeIntent.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            query = query.where(TradeIntent.created_at <= dt_to)
        except ValueError:
            pass
    result = await session.execute(query)
    return {"count": result.scalar() or 0}


@router.get("/stats")
async def trade_stats(session: DbSession):
    """Aggregate trade statistics."""
    total = await session.execute(select(func.count(TradeIntent.id)))
    filled = await session.execute(
        select(func.count(TradeIntent.id)).where(TradeIntent.status == "FILLED")
    )
    rejected = await session.execute(
        select(func.count(TradeIntent.id)).where(TradeIntent.status == "REJECTED")
    )
    pending = await session.execute(
        select(func.count(TradeIntent.id)).where(TradeIntent.status == "PENDING")
    )
    return {
        "total": total.scalar() or 0,
        "filled": filled.scalar() or 0,
        "rejected": rejected.scalar() or 0,
        "pending": pending.scalar() or 0,
    }


@router.get("/portfolio-summary")
async def portfolio_summary(session: DbSession):
    """Aggregate portfolio metrics across all agents."""
    # Total P&L from closed trades
    total_pnl = await session.execute(
        select(func.coalesce(func.sum(AgentTrade.pnl_dollar), 0.0))
        .where(AgentTrade.status == "closed")
    )
    # Open positions count
    open_count = await session.execute(
        select(func.count(AgentTrade.id)).where(AgentTrade.status == "open")
    )
    # Win rate
    total_closed = await session.execute(
        select(func.count(AgentTrade.id)).where(AgentTrade.status == "closed")
    )
    winning = await session.execute(
        select(func.count(AgentTrade.id)).where(
            AgentTrade.status == "closed", AgentTrade.pnl_dollar > 0
        )
    )
    total_closed_val = total_closed.scalar() or 0
    winning_val = winning.scalar() or 0

    # Today's P&L
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min).replace(tzinfo=timezone.utc)
    today_pnl = await session.execute(
        select(func.coalesce(func.sum(AgentTrade.pnl_dollar), 0.0))
        .where(AgentTrade.exit_time >= today_start, AgentTrade.status == "closed")
    )

    # Per-agent breakdown
    agent_stats = await session.execute(
        select(
            AgentTrade.agent_id,
            func.count(AgentTrade.id).label("total_trades"),
            func.count(case((AgentTrade.status == "open", 1))).label("open_positions"),
            func.coalesce(
                func.sum(case((AgentTrade.status == "closed", AgentTrade.pnl_dollar))), 0.0
            ).label("total_pnl"),
            func.coalesce(func.sum(case(
                (AgentTrade.exit_time >= today_start, AgentTrade.pnl_dollar)
            )), 0.0).label("today_pnl"),
        )
        .group_by(AgentTrade.agent_id)
    )
    agent_rows = agent_stats.all()

    # Enrich with agent names
    agent_ids = [r.agent_id for r in agent_rows]
    agents_result = await session.execute(
        select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
    ) if agent_ids else None
    name_map = {str(r.id): r.name for r in agents_result.all()} if agents_result else {}

    per_agent = []
    for r in agent_rows:
        per_agent.append({
            "agent_id": str(r.agent_id),
            "agent_name": name_map.get(str(r.agent_id), "Unknown"),
            "total_trades": r.total_trades,
            "open_positions": r.open_positions,
            "total_pnl": float(r.total_pnl),
            "today_pnl": float(r.today_pnl),
        })

    return {
        "total_pnl": float(total_pnl.scalar() or 0),
        "today_pnl": float(today_pnl.scalar() or 0),
        "open_positions": open_count.scalar() or 0,
        "total_closed_trades": total_closed_val,
        "win_rate": winning_val / total_closed_val if total_closed_val > 0 else 0.0,
        "per_agent": per_agent,
    }


@router.get("/today")
async def today_trades(session: DbSession, limit: int = Query(100, ge=1, le=500)):
    """Get all trades entered or exited today."""
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min).replace(tzinfo=timezone.utc)
    result = await session.execute(
        select(AgentTrade)
        .where(
            (AgentTrade.entry_time >= today_start) | (AgentTrade.exit_time >= today_start)
        )
        .order_by(desc(AgentTrade.created_at))
        .limit(limit)
    )
    trades = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "agent_id": str(t.agent_id),
            "ticker": t.ticker,
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl_dollar": t.pnl_dollar,
            "pnl_pct": t.pnl_pct,
            "status": t.status,
            "decision_status": t.decision_status,
            "model_confidence": t.model_confidence,
            "reasoning": t.reasoning,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        }
        for t in trades
    ]


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: str, session: DbSession):
    """Get a single trade intent by ID."""
    result = await session.execute(
        select(TradeIntent).where(TradeIntent.id == uuid.UUID(trade_id))
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return TradeResponse.from_model(trade)


class TradeNotesUpdate(BaseModel):
    notes: str


@router.patch("/{trade_id}/notes", response_model=TradeResponse)
async def update_trade_notes(trade_id: str, payload: TradeNotesUpdate, session: DbSession):
    """Update the notes/journal entry for a trade."""
    result = await session.execute(
        select(TradeIntent).where(TradeIntent.id == uuid.UUID(trade_id))
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    extra = dict(trade.extra_data or {})
    extra["notes"] = payload.notes
    trade.extra_data = extra
    await session.commit()
    await session.refresh(trade)
    return TradeResponse.from_model(trade)
