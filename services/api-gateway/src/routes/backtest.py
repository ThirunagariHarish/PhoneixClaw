import asyncio
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.backtest.discord_fetcher import fetch_channel_history
from shared.backtest.engine import run_backtest
from shared.crypto.credentials import decrypt_credentials
from shared.models.database import AsyncSessionLocal, get_session
from shared.models.trade import BacktestRun, BacktestTrade, Channel, DataSource, NotificationLog, TradingAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


class BacktestCreate(BaseModel):
    start_date: str  # ISO format
    end_date: str
    data_source_id: str
    channel_id: str
    trading_account_id: str
    name: str | None = None
    profit_target: float = 0.30
    stop_loss: float = 0.20


class BacktestRunResponse(BaseModel):
    id: str
    name: str | None
    data_source_id: str | None
    channel_id: str | None
    trading_account_id: str | None
    start_date: str
    end_date: str
    status: str
    summary: dict | None
    error_message: str | None
    created_at: str


class BacktestTradeResponse(BaseModel):
    id: int
    trade_id: str
    ticker: str
    strike: float
    option_type: str
    action: str
    quantity: str
    entry_price: float
    exit_price: float | None
    entry_ts: str
    exit_ts: str | None
    exit_reason: str | None
    realized_pnl: float | None
    raw_message: str | None


def _run_response(r: BacktestRun) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "data_source_id": str(r.data_source_id) if r.data_source_id else None,
        "channel_id": str(r.channel_id) if r.channel_id else None,
        "trading_account_id": str(r.trading_account_id) if r.trading_account_id else None,
        "start_date": r.start_date.isoformat() if r.start_date else "",
        "end_date": r.end_date.isoformat() if r.end_date else "",
        "status": r.status,
        "summary": r.summary,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


def _trade_response(t: BacktestTrade) -> dict:
    return {
        "id": t.id,
        "trade_id": str(t.trade_id),
        "ticker": t.ticker,
        "strike": float(t.strike),
        "option_type": t.option_type,
        "action": t.action,
        "quantity": t.quantity,
        "entry_price": float(t.entry_price),
        "exit_price": float(t.exit_price) if t.exit_price else None,
        "entry_ts": t.entry_ts.isoformat() if t.entry_ts else "",
        "exit_ts": t.exit_ts.isoformat() if t.exit_ts else None,
        "exit_reason": t.exit_reason,
        "realized_pnl": float(t.realized_pnl) if t.realized_pnl is not None else None,
        "raw_message": t.raw_message,
    }


async def _run_backtest_background(
    run_id: uuid.UUID,
    user_id: str,
    creds_encrypted: str,
    auth_type: str,
    channel_identifier: str,
    start_dt: datetime,
    end_dt: datetime,
    profit_target: float,
    stop_loss: float,
    run_name: str | None,
) -> None:
    """Execute backtest in background, update DB when done, and create notification."""
    async with AsyncSessionLocal() as session:
        run = await session.get(BacktestRun, run_id)
        if not run:
            return
        try:
            creds = decrypt_credentials(creds_encrypted)
            token = creds.get("user_token") or creds.get("bot_token", "")
            if not token:
                raise ValueError("No Discord token in credentials")

            channel_id_int = int(channel_identifier.strip())

            messages = await fetch_channel_history(
                channel_id=channel_id_int,
                after=start_dt,
                before=end_dt,
                token=token,
                auth_type=auth_type,
            )

            trade_dicts, summary = run_backtest(
                messages,
                profit_target=profit_target,
                stop_loss=stop_loss,
            )

            run.status = "completed"
            run.summary = summary
            run.error_message = None

            for td in trade_dicts:
                exp = None
                if td.get("expiration"):
                    try:
                        exp = datetime.strptime(td["expiration"], "%Y-%m-%d")
                    except (ValueError, TypeError):
                        pass
                bt = BacktestTrade(
                    backtest_run_id=run.id,
                    trade_id=uuid.UUID(td["trade_id"]),
                    ticker=td["ticker"],
                    strike=td["strike"],
                    option_type=td["option_type"],
                    expiration=exp,
                    action=td["action"],
                    quantity=td["quantity"],
                    entry_price=td["entry_price"],
                    exit_price=td.get("exit_price"),
                    entry_ts=td["entry_ts"],
                    exit_ts=td.get("exit_ts"),
                    exit_reason=td.get("exit_reason"),
                    realized_pnl=td.get("realized_pnl"),
                    raw_message=td.get("raw_message"),
                )
                session.add(bt)

            total_pnl = summary.get("total_pnl", 0) if summary else 0
            total_trades = summary.get("total_trades", 0) if summary else 0
            notif = NotificationLog(
                user_id=uuid.UUID(user_id),
                notification_type="backtest",
                channel="in_app",
                priority="normal",
                title="Backtest Completed",
                body=f"{run_name or 'Backtest'}: {total_trades} trades, P&L ${total_pnl:.2f}",
                status="SENT",
                read=False,
            )
            session.add(notif)

        except ValueError as e:
            run.status = "failed"
            run.error_message = str(e)[:500]
            logger.warning("Backtest failed (user=%s): %s", user_id, e)
            notif = NotificationLog(
                user_id=uuid.UUID(user_id),
                notification_type="backtest",
                channel="in_app",
                priority="normal",
                title="Backtest Failed",
                body=f"{run_name or 'Backtest'}: {str(e)[:200]}",
                status="SENT",
                read=False,
            )
            session.add(notif)
        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)[:500]
            logger.exception("Backtest failed for run %s", run.id)
            notif = NotificationLog(
                user_id=uuid.UUID(user_id),
                notification_type="backtest",
                channel="in_app",
                priority="normal",
                title="Backtest Failed",
                body=f"{run_name or 'Backtest'}: {str(e)[:200]}",
                status="SENT",
                read=False,
            )
            session.add(notif)

        await session.commit()


@router.post("", response_model=BacktestRunResponse, status_code=201)
async def create_and_run_backtest(
    req: BacktestCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id

    start_dt = datetime.fromisoformat(req.start_date.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(req.end_date.replace("Z", "+00:00"))
    if start_dt >= end_dt:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    data_source = await session.get(DataSource, uuid.UUID(req.data_source_id))
    if not data_source or str(data_source.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Data source not found")

    channel = await session.get(Channel, uuid.UUID(req.channel_id))
    if not channel or channel.data_source_id != uuid.UUID(req.data_source_id):
        raise HTTPException(status_code=404, detail="Channel not found")

    account = await session.get(TradingAccount, uuid.UUID(req.trading_account_id))
    if not account or str(account.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Trading account not found")

    run = BacktestRun(
        user_id=uuid.UUID(user_id),
        name=req.name,
        data_source_id=uuid.UUID(req.data_source_id),
        channel_id=uuid.UUID(req.channel_id),
        trading_account_id=uuid.UUID(req.trading_account_id),
        start_date=start_dt,
        end_date=end_dt,
        status="running",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    asyncio.create_task(
        _run_backtest_background(
            run_id=run.id,
            user_id=user_id,
            creds_encrypted=data_source.credentials_encrypted,
            auth_type=data_source.auth_type or "user_token",
            channel_identifier=channel.channel_identifier,
            start_dt=start_dt,
            end_dt=end_dt,
            profit_target=req.profit_target,
            stop_loss=req.stop_loss,
            run_name=req.name,
        )
    )

    return _run_response(run)


@router.get("", response_model=list)
async def list_backtest_runs(
    request: Request,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = (
        select(BacktestRun)
        .where(BacktestRun.user_id == uuid.UUID(user_id))
        .order_by(desc(BacktestRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return [_run_response(r) for r in result.scalars().all()]


@router.get("/{run_id}", response_model=BacktestRunResponse)
async def get_backtest_run(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(BacktestRun).where(
            BacktestRun.id == uuid.UUID(run_id),
            BacktestRun.user_id == uuid.UUID(user_id),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return _run_response(run)


@router.get("/{run_id}/trades")
async def get_backtest_trades(
    run_id: str,
    request: Request,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(BacktestRun).where(
            BacktestRun.id == uuid.UUID(run_id),
            BacktestRun.user_id == uuid.UUID(user_id),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    stmt = (
        select(BacktestTrade)
        .where(BacktestTrade.backtest_run_id == uuid.UUID(run_id))
        .order_by(BacktestTrade.entry_ts)
        .limit(limit)
        .offset(offset)
    )
    trades_result = await session.execute(stmt)
    trades = trades_result.scalars().all()
    return {"trades": [_trade_response(t) for t in trades]}


@router.delete("/{run_id}", status_code=204)
async def delete_backtest_run(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(BacktestRun).where(
            BacktestRun.id == uuid.UUID(run_id),
            BacktestRun.user_id == uuid.UUID(user_id),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    await session.delete(run)
    await session.commit()
