import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import Position

router = APIRouter(prefix="/api/v1/positions", tags=["positions"])


@router.get("")
async def list_positions(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = select(Position).where(Position.user_id == uuid.UUID(user_id))
    if status:
        stmt = stmt.where(Position.status == status)
    stmt = stmt.order_by(desc(Position.opened_at)).limit(limit).offset(offset)
    result = await session.execute(stmt)
    positions = result.scalars().all()
    return [_pos_response(p) for p in positions]


@router.get("/{position_id}")
async def get_position(
    position_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(Position).where(Position.id == position_id, Position.user_id == uuid.UUID(user_id))
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return _pos_response(pos)


@router.post("/{position_id}/close")
async def close_position(
    position_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Manually close a position by publishing an exit signal."""
    user_id = request.state.user_id
    result = await session.execute(
        select(Position).where(
            Position.id == position_id,
            Position.user_id == uuid.UUID(user_id),
            Position.status == "OPEN",
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Open position not found")

    from services.api_gateway.src.routes.chat import _kafka_producer

    if _kafka_producer and _kafka_producer.is_started:
        exit_signal = {
            "position_id": pos.id,
            "user_id": user_id,
            "trading_account_id": str(pos.trading_account_id),
            "ticker": pos.ticker,
            "strike": float(pos.strike),
            "option_type": pos.option_type,
            "expiration": pos.expiration.strftime("%Y-%m-%d") if pos.expiration else None,
            "action": "MANUAL_EXIT",
            "quantity": pos.quantity,
            "entry_price": float(pos.avg_entry_price),
            "current_price": float(pos.avg_entry_price),
            "broker_symbol": pos.broker_symbol,
        }
        await _kafka_producer.send(
            "exit-signals", value=exit_signal, key=str(position_id)
        )
        return {"status": "closing", "position_id": position_id}

    pos.status = "CLOSED"
    pos.close_reason = "MANUAL"
    pos.closed_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "closed", "position_id": position_id}


def _pos_response(p: Position) -> dict:
    return {
        "id": p.id,
        "ticker": p.ticker,
        "strike": float(p.strike),
        "option_type": p.option_type,
        "expiration": p.expiration.strftime("%Y-%m-%d") if p.expiration else None,
        "quantity": p.quantity,
        "avg_entry_price": float(p.avg_entry_price),
        "total_cost": float(p.total_cost),
        "profit_target": float(p.profit_target),
        "stop_loss": float(p.stop_loss),
        "high_water_mark": float(p.high_water_mark) if p.high_water_mark else None,
        "broker_symbol": p.broker_symbol,
        "status": p.status,
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "close_reason": p.close_reason,
        "realized_pnl": float(p.realized_pnl) if p.realized_pnl else None,
    }
