"""
Positions API routes: list open/closed positions, position summary.

M1.10: Positions Tab backend.
Reference: PRD Section 3.2.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from apps.api.src.deps import DbSession
from shared.db.models.trade import Position

router = APIRouter(prefix="/api/v2/positions", tags=["positions"])


class PositionResponse(BaseModel):
    id: str
    agent_id: str
    account_id: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    stop_loss: float | None
    take_profit: float | None
    status: str
    exit_price: float | None
    exit_reason: str | None
    opened_at: str
    closed_at: str | None

    @classmethod
    def from_model(cls, p: Position) -> "PositionResponse":
        return cls(
            id=str(p.id),
            agent_id=str(p.agent_id),
            account_id=p.account_id,
            symbol=p.symbol,
            side=p.side,
            qty=p.qty,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
            realized_pnl=p.realized_pnl,
            stop_loss=p.stop_loss,
            take_profit=p.take_profit,
            status=p.status,
            exit_price=p.exit_price,
            exit_reason=p.exit_reason,
            opened_at=p.opened_at.isoformat() if p.opened_at else "",
            closed_at=p.closed_at.isoformat() if p.closed_at else None,
        )


@router.get("", response_model=list[PositionResponse])
async def list_positions(
    session: DbSession,
    status_filter: str | None = Query("OPEN", alias="status"),
    symbol: str | None = None,
    agent_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List positions with optional filters. Defaults to OPEN positions."""
    query = select(Position).order_by(desc(Position.opened_at))
    if status_filter:
        query = query.where(Position.status == status_filter)
    if symbol:
        query = query.where(Position.symbol == symbol.upper())
    if agent_id:
        query = query.where(Position.agent_id == uuid.UUID(agent_id))
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    return [PositionResponse.from_model(p) for p in result.scalars().all()]


@router.get("/closed", response_model=list[PositionResponse])
async def list_closed_positions(
    session: DbSession,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List closed positions."""
    result = await session.execute(
        select(Position)
        .where(Position.status == "CLOSED")
        .order_by(desc(Position.closed_at))
        .limit(limit)
        .offset(offset)
    )
    return [PositionResponse.from_model(p) for p in result.scalars().all()]


@router.get("/summary")
async def position_summary(session: DbSession):
    """Aggregate position summary across all accounts."""
    open_count = await session.execute(
        select(func.count(Position.id)).where(Position.status == "OPEN")
    )
    total_unrealized = await session.execute(
        select(func.coalesce(func.sum(Position.unrealized_pnl), 0)).where(Position.status == "OPEN")
    )
    total_realized = await session.execute(
        select(func.coalesce(func.sum(Position.realized_pnl), 0)).where(Position.status == "CLOSED")
    )
    return {
        "open_positions": open_count.scalar() or 0,
        "total_unrealized_pnl": float(total_unrealized.scalar() or 0),
        "total_realized_pnl": float(total_realized.scalar() or 0),
    }


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(position_id: str, session: DbSession):
    """Get a single position by ID."""
    result = await session.execute(
        select(Position).where(Position.id == uuid.UUID(position_id))
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    return PositionResponse.from_model(position)


class UpdatePositionRequest(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None


@router.patch("/{position_id}", response_model=PositionResponse)
async def update_position(position_id: str, payload: UpdatePositionRequest, session: DbSession):
    """Update stop-loss and/or take-profit for an open position."""
    result = await session.execute(
        select(Position).where(Position.id == uuid.UUID(position_id))
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    if position.status != "OPEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Position is not open")
    if payload.stop_loss is not None:
        position.stop_loss = payload.stop_loss
    if payload.take_profit is not None:
        position.take_profit = payload.take_profit
    await session.commit()
    await session.refresh(position)
    return PositionResponse.from_model(position)


class ClosePositionRequest(BaseModel):
    exit_price: float
    exit_reason: str = "manual_close"


@router.post("/{position_id}/close", response_model=PositionResponse)
async def close_position(position_id: str, payload: ClosePositionRequest, session: DbSession):
    """Manually close an open position."""
    from datetime import datetime
    from datetime import timezone as tz
    result = await session.execute(
        select(Position).where(Position.id == uuid.UUID(position_id))
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    if position.status != "OPEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Position is not open")
    position.status = "CLOSED"
    position.exit_price = payload.exit_price
    position.exit_reason = payload.exit_reason
    position.closed_at = datetime.now(tz.utc)
    pnl_multiplier = 1 if position.side == "long" else -1
    position.realized_pnl = (payload.exit_price - position.entry_price) * position.qty * pnl_multiplier
    position.unrealized_pnl = 0
    await session.commit()
    await session.refresh(position)
    return PositionResponse.from_model(position)
