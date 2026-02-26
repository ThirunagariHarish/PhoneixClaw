import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.broker.alpaca_adapter import parse_occ_symbol
from shared.broker.factory import create_broker_adapter
from shared.models.database import get_session
from shared.models.trade import Position, TradingAccount

logger = logging.getLogger(__name__)

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

    # Open positions: fetch from Alpaca for each user account
    if status == "OPEN" or status is None:
        alpaca_positions: list[dict] = []
        acct_stmt = select(TradingAccount).where(
            TradingAccount.user_id == uuid.UUID(user_id),
            TradingAccount.enabled,
            TradingAccount.broker_type == "alpaca",
        )
        acct_result = await session.execute(acct_stmt)
        accounts = acct_result.scalars().all()

        for account in accounts:
            try:
                adapter = create_broker_adapter(
                    account.broker_type, account.credentials_encrypted, account.paper_mode
                )
                try:
                    raw = await adapter.get_positions()
                    for p in raw:
                        parsed = _alpaca_pos_to_response(p, str(account.id))
                        if parsed:
                            alpaca_positions.append(parsed)
                finally:
                    await adapter.close()
            except Exception as e:
                logger.warning("Failed to fetch Alpaca positions for account %s: %s", account.id, e)

        if status == "OPEN":
            return alpaca_positions[:limit]
        # status is None: return open from Alpaca, then closed from DB
        db_stmt = select(Position).where(
            Position.user_id == uuid.UUID(user_id),
            Position.status == "CLOSED",
        )
        db_stmt = db_stmt.order_by(desc(Position.closed_at)).limit(limit).offset(0)
        db_result = await session.execute(db_stmt)
        db_positions = db_result.scalars().all()
        return [_pos_response(p) for p in alpaca_positions] + [_pos_response(p) for p in db_positions]

    # Closed only: from DB
    stmt = select(Position).where(Position.user_id == uuid.UUID(user_id))
    if status:
        stmt = stmt.where(Position.status == status)
    stmt = stmt.order_by(desc(Position.opened_at)).limit(limit).offset(offset)
    result = await session.execute(stmt)
    positions = result.scalars().all()
    return [_pos_response(p) for p in positions]


def _alpaca_pos_to_response(p: dict, account_id: str) -> dict | None:
    """Convert Alpaca position dict to API response format."""
    symbol = p["symbol"]
    qty = p["qty"]
    avg_entry = p["avg_entry_price"]
    total_cost = avg_entry * abs(qty)
    parsed = parse_occ_symbol(symbol)
    if parsed:
        ticker = parsed["ticker"]
        strike = parsed["strike"]
        option_type = parsed["option_type"]
        expiration = parsed["expiration"]
    else:
        ticker = symbol
        strike = 0.0
        option_type = ""
        expiration = None
    return {
        "id": f"alpaca:{account_id}:{symbol}",
        "ticker": ticker,
        "strike": strike,
        "option_type": option_type,
        "expiration": expiration,
        "quantity": abs(qty),
        "avg_entry_price": avg_entry,
        "total_cost": total_cost,
        "profit_target": 0.30,
        "stop_loss": 0.20,
        "high_water_mark": None,
        "broker_symbol": symbol,
        "status": "OPEN",
        "opened_at": None,
        "closed_at": None,
        "close_reason": None,
        "realized_pnl": None,
        "account_id": account_id,
        "unrealized_pl": p.get("unrealized_pl"),
        "current_price": p.get("current_price"),
    }


@router.get("/{position_id}")
async def get_position(
    position_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Get a single position. Only DB positions are supported (Alpaca positions are listed only)."""
    user_id = request.state.user_id
    if position_id.startswith("alpaca:"):
        raise HTTPException(status_code=404, detail="Use list positions for Alpaca positions")
    try:
        pid = int(position_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Position not found")
    result = await session.execute(
        select(Position).where(Position.id == pid, Position.user_id == uuid.UUID(user_id))
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return _pos_response(pos)


@router.post("/{position_id}/close")
async def close_position(
    position_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Close a position. Alpaca: closes via broker. DB: publishes exit signal."""
    user_id = request.state.user_id

    # Alpaca position: close directly via broker
    if position_id.startswith("alpaca:"):
        parts = position_id.split(":", 2)
        if len(parts) != 3:
            raise HTTPException(status_code=400, detail="Invalid Alpaca position id")
        _, account_id, symbol = parts
        result = await session.execute(
            select(TradingAccount).where(
                TradingAccount.id == uuid.UUID(account_id),
                TradingAccount.user_id == uuid.UUID(user_id),
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        adapter = create_broker_adapter(
            account.broker_type, account.credentials_encrypted, account.paper_mode
        )
        try:
            ok = await adapter.close_position(symbol)
            if ok:
                return {"status": "closed", "position_id": position_id}
            raise HTTPException(status_code=500, detail="Failed to close position")
        finally:
            await adapter.close()

    # DB position: publish exit signal
    try:
        pid = int(position_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Position not found")
    result = await session.execute(
        select(Position).where(
            Position.id == pid,
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
        return {"status": "closing", "position_id": pid}

    pos.status = "CLOSED"
    pos.close_reason = "MANUAL"
    pos.closed_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "closed", "position_id": pid}


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
