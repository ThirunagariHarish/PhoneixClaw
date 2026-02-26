import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import Trade, TradingAccount

router = APIRouter(prefix="/api/v1/trades", tags=["trades"])


def _trade_response(t: Trade) -> dict:
    return {
        "id": t.id,
        "trade_id": str(t.trade_id),
        "ticker": t.ticker,
        "strike": float(t.strike),
        "option_type": t.option_type,
        "action": t.action,
        "price": float(t.price),
        "quantity": t.quantity,
        "status": t.status,
        "source": t.source,
        "error_message": t.error_message,
        "rejection_reason": t.rejection_reason,
        "broker_order_id": t.broker_order_id,
        "raw_message": t.raw_message,
        "source_author": t.source_author,
        "approved_by": t.approved_by,
        "approved_at": t.approved_at.isoformat() if t.approved_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "processed_at": t.processed_at.isoformat() if t.processed_at else None,
        "buffered_price": float(t.buffered_price) if t.buffered_price else None,
        "fill_price": float(t.fill_price) if t.fill_price else None,
        "realized_pnl": float(t.realized_pnl) if t.realized_pnl else None,
        "execution_latency_ms": t.execution_latency_ms,
    }


@router.get("")
async def list_trades(
    request: Request,
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = select(Trade).where(Trade.user_id == uuid.UUID(user_id))
    if status:
        stmt = stmt.where(Trade.status == status)
    stmt = stmt.order_by(desc(Trade.created_at)).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [_trade_response(t) for t in result.scalars().all()]


@router.get("/stats")
async def trade_stats(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = uuid.UUID(request.state.user_id)
    total = (await session.execute(
        select(func.count(Trade.id)).where(Trade.user_id == user_id)
    )).scalar() or 0
    executed = (await session.execute(
        select(func.count(Trade.id)).where(Trade.user_id == user_id, Trade.status == "EXECUTED")
    )).scalar() or 0
    rejected = (await session.execute(
        select(func.count(Trade.id)).where(Trade.user_id == user_id, Trade.status == "REJECTED")
    )).scalar() or 0
    errored = (await session.execute(
        select(func.count(Trade.id)).where(Trade.user_id == user_id, Trade.status == "ERROR")
    )).scalar() or 0
    return {"total": total, "executed": executed, "rejected": rejected, "errored": errored}


@router.get("/{trade_id}")
async def get_trade(
    trade_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(Trade).where(
            Trade.trade_id == uuid.UUID(trade_id),
            Trade.user_id == uuid.UUID(user_id),
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return _trade_response(trade)


@router.post("/{trade_id}/approve")
async def approve_trade(
    trade_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(Trade).where(
            Trade.trade_id == uuid.UUID(trade_id),
            Trade.user_id == uuid.UUID(user_id),
            Trade.status == "PENDING",
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Pending trade not found")

    trade.status = "IN_PROGRESS"
    trade.approved_by = "dashboard"
    trade.approved_at = datetime.now(timezone.utc)

    if not trade.trading_account_id:
        acc_result = await session.execute(
            select(TradingAccount).where(
                TradingAccount.user_id == uuid.UUID(user_id),
                TradingAccount.enabled.is_(True),
            ).limit(1)
        )
        account = acc_result.scalar_one_or_none()
        if account:
            trade.trading_account_id = account.id

    await session.commit()

    from services.api_gateway.src.routes.chat import _kafka_producer
    if _kafka_producer and _kafka_producer.is_started:
        ta_id = str(trade.trading_account_id) if trade.trading_account_id else None
        approved_trade = {
            "trade_id": str(trade.trade_id),
            "user_id": user_id,
            "trading_account_id": ta_id,
            "ticker": trade.ticker,
            "strike": float(trade.strike),
            "option_type": trade.option_type,
            "expiration": trade.expiration.strftime("%Y-%m-%d") if trade.expiration else None,
            "action": trade.action,
            "quantity": trade.quantity,
            "price": float(trade.price),
            "source": trade.source,
            "raw_message": trade.raw_message,
            "status": "IN_PROGRESS",
            "approved_by": "dashboard",
        }
        await _kafka_producer.send("approved-trades", value=approved_trade, key=str(trade.trade_id))

    return _trade_response(trade)


@router.post("/{trade_id}/reject")
async def reject_trade(
    trade_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    reason = body.get("reason", "Rejected by user")

    result = await session.execute(
        select(Trade).where(
            Trade.trade_id == uuid.UUID(trade_id),
            Trade.user_id == uuid.UUID(user_id),
            Trade.status == "PENDING",
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Pending trade not found")

    trade.status = "REJECTED"
    trade.rejection_reason = reason
    trade.processed_at = datetime.now(timezone.utc)
    await session.commit()
    return _trade_response(trade)
