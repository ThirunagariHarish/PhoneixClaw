import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import UserWatchlist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    ticker: str
    notes: str | None = None


class WatchlistItem(BaseModel):
    id: str
    ticker: str
    notes: str | None
    created_at: str


@router.get("", response_model=list[WatchlistItem])
async def list_watchlist(request: Request, session: AsyncSession = Depends(get_session)):
    uid = uuid.UUID(request.state.user_id)
    result = await session.execute(
        select(UserWatchlist)
        .where(UserWatchlist.user_id == uid)
        .order_by(UserWatchlist.created_at.desc())
    )
    items = result.scalars().all()
    return [
        WatchlistItem(
            id=str(w.id),
            ticker=w.ticker,
            notes=w.notes,
            created_at=w.created_at.isoformat(),
        )
        for w in items
    ]


@router.post("", response_model=WatchlistItem, status_code=201)
async def add_to_watchlist(
    body: WatchlistAdd,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    uid = uuid.UUID(request.state.user_id)
    ticker = body.ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(400, "Invalid ticker symbol")

    existing = await session.execute(
        select(UserWatchlist).where(
            UserWatchlist.user_id == uid,
            UserWatchlist.ticker == ticker,
        )
    )
    if existing.scalars().first():
        raise HTTPException(409, f"{ticker} is already in your watchlist")

    item = UserWatchlist(
        id=uuid.uuid4(),
        user_id=uid,
        ticker=ticker,
        notes=body.notes,
        created_at=datetime.now(timezone.utc),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    return WatchlistItem(
        id=str(item.id),
        ticker=item.ticker,
        notes=item.notes,
        created_at=item.created_at.isoformat(),
    )


@router.delete("/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    uid = uuid.UUID(request.state.user_id)
    result = await session.execute(
        delete(UserWatchlist).where(
            UserWatchlist.user_id == uid,
            UserWatchlist.ticker == ticker.upper(),
        )
    )
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(404, f"{ticker.upper()} not found in watchlist")
    return {"status": "removed", "ticker": ticker.upper()}
