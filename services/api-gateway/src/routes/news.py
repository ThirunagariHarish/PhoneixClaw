import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import cast, desc, func, select
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from shared.crypto.credentials import encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import NewsConnection, NewsHeadline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/news", tags=["news"])


class HeadlineResponse(BaseModel):
    id: str
    source_api: str
    title: str
    summary: str | None
    url: str | None
    image_url: str | None
    author: str | None
    tickers: list[str]
    category: str | None
    sentiment_label: str | None
    sentiment_score: float | None
    importance_score: float | None
    cluster_id: str | None
    cluster_size: int
    published_at: str | None
    created_at: str


class ConnectionCreate(BaseModel):
    source_api: str
    display_name: str
    api_key: str | None = None
    config: dict = {}


class ConnectionResponse(BaseModel):
    id: str
    source_api: str
    display_name: str
    enabled: bool
    last_poll_at: str | None
    error_message: str | None
    created_at: str


@router.get("/headlines")
async def list_headlines(
    request: Request,
    source: str | None = Query(None),
    ticker: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(NewsHeadline).order_by(desc(NewsHeadline.importance_score), desc(NewsHeadline.created_at))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    stmt = stmt.where(NewsHeadline.created_at >= cutoff)

    if source:
        stmt = stmt.where(NewsHeadline.source_api == source)

    if ticker:
        ticker_upper = ticker.upper()
        ticker_filter = NewsHeadline.tickers.op("@>")(cast([ticker_upper], PG_JSONB))
        stmt = stmt.where(ticker_filter)

    count_stmt = select(func.count(NewsHeadline.id)).where(NewsHeadline.created_at >= cutoff)
    if source:
        count_stmt = count_stmt.where(NewsHeadline.source_api == source)
    if ticker:
        count_stmt = count_stmt.where(NewsHeadline.tickers.op("@>")(cast([ticker_upper], PG_JSONB)))
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    headlines = [
        HeadlineResponse(
            id=str(h.id),
            source_api=h.source_api,
            title=h.title,
            summary=h.summary,
            url=h.url,
            image_url=h.image_url,
            author=h.author,
            tickers=h.tickers or [],
            category=h.category,
            sentiment_label=h.sentiment_label,
            sentiment_score=float(h.sentiment_score) if h.sentiment_score else None,
            importance_score=float(h.importance_score) if h.importance_score else None,
            cluster_id=h.cluster_id,
            cluster_size=h.cluster_size or 1,
            published_at=h.published_at.isoformat() if h.published_at else None,
            created_at=h.created_at.isoformat() if h.created_at else None,
        )
        for h in rows
    ]
    return {"total": total, "headlines": headlines}


@router.get("/connections")
async def list_connections(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(NewsConnection)
        .where(NewsConnection.user_id == uuid.UUID(user_id))
        .order_by(NewsConnection.created_at)
    )
    return [_conn_response(c) for c in result.scalars().all()]


@router.post("/connections", status_code=201)
async def create_connection(
    req: ConnectionCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id

    existing = await session.execute(
        select(NewsConnection).where(
            NewsConnection.user_id == uuid.UUID(user_id),
            NewsConnection.source_api == req.source_api,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Connection for {req.source_api} already exists")

    api_key_enc = None
    if req.api_key:
        api_key_enc = encrypt_credentials({"api_key": req.api_key})

    conn = NewsConnection(
        user_id=uuid.UUID(user_id),
        source_api=req.source_api,
        display_name=req.display_name,
        api_key_encrypted=api_key_enc,
        config=req.config,
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return _conn_response(conn)


@router.delete("/connections/{conn_id}", status_code=204)
async def delete_connection(
    conn_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(NewsConnection).where(
            NewsConnection.id == uuid.UUID(conn_id),
            NewsConnection.user_id == uuid.UUID(user_id),
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await session.delete(conn)
    await session.commit()


@router.patch("/connections/{conn_id}/toggle")
async def toggle_connection(
    conn_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(NewsConnection).where(
            NewsConnection.id == uuid.UUID(conn_id),
            NewsConnection.user_id == uuid.UUID(user_id),
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn.enabled = not conn.enabled
    await session.commit()
    await session.refresh(conn)
    return _conn_response(conn)


def _conn_response(c: NewsConnection) -> ConnectionResponse:
    return ConnectionResponse(
        id=str(c.id),
        source_api=c.source_api,
        display_name=c.display_name,
        enabled=c.enabled,
        last_poll_at=c.last_poll_at.isoformat() if c.last_poll_at else None,
        error_message=c.error_message,
        created_at=c.created_at.isoformat(),
    )
