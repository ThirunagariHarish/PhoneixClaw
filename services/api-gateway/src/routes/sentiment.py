import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import SentimentAlert, SentimentMessage, TickerSentiment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sentiment", tags=["sentiment"])


class TickerSentimentResponse(BaseModel):
    ticker: str
    sentiment_label: str
    sentiment_score: float
    message_count: int
    mention_change_pct: float | None
    bullish_count: int
    bearish_count: int
    neutral_count: int
    period_start: str
    sparkline: list[float]


class SentimentMessageResponse(BaseModel):
    id: str
    channel_name: str | None
    author: str | None
    content: str
    sentiment_label: str | None
    sentiment_score: float | None
    confidence: float | None
    message_timestamp: str | None
    created_at: str | None


class AlertCreate(BaseModel):
    ticker: str | None = None
    alert_type: str
    config: dict = {}
    enabled: bool = True


class AlertResponse(BaseModel):
    id: str
    ticker: str | None
    alert_type: str
    config: dict
    enabled: bool
    last_triggered_at: str | None
    created_at: str


@router.get("/tickers")
async def list_ticker_sentiments(
    request: Request,
    sentiment: str | None = Query(None),
    min_mentions: int = Query(0, ge=0),
    time_range: str = Query("3h"),
    watchlist_only: bool = Query(False),
    search: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    hours_map = {"1h": 1, "3h": 3, "6h": 6, "12h": 12, "24h": 24, "7d": 168}
    hours = hours_map.get(time_range, 3)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(TickerSentiment)
        .where(TickerSentiment.period_start >= cutoff)
        .order_by(desc(TickerSentiment.updated_at))
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    ticker_latest: dict[str, TickerSentiment] = {}
    ticker_sparklines: dict[str, list[tuple[datetime, float]]] = {}
    for row in rows:
        t = row.ticker
        if t not in ticker_latest or row.period_start > ticker_latest[t].period_start:
            ticker_latest[t] = row
        ticker_sparklines.setdefault(t, []).append(
            (row.period_start, float(row.sentiment_score))
        )

    results = []
    for ticker, agg in ticker_latest.items():
        if sentiment and agg.sentiment_label.lower() != sentiment.lower():
            continue
        if agg.message_count < min_mentions:
            continue
        if search and search.upper() not in ticker.upper():
            continue

        spark_data = sorted(ticker_sparklines.get(ticker, []), key=lambda x: x[0])
        sparkline = [s[1] for s in spark_data[-6:]]

        results.append(TickerSentimentResponse(
            ticker=ticker,
            sentiment_label=agg.sentiment_label,
            sentiment_score=float(agg.sentiment_score),
            message_count=agg.message_count,
            mention_change_pct=float(agg.mention_change_pct) if agg.mention_change_pct else None,
            bullish_count=agg.bullish_count,
            bearish_count=agg.bearish_count,
            neutral_count=agg.neutral_count,
            period_start=agg.period_start.isoformat(),
            sparkline=sparkline,
        ))

    results.sort(key=lambda x: x.message_count, reverse=True)

    if watchlist_only:
        user_id = request.state.user_id
        from shared.models.trade import UserWatchlist
        wl_result = await session.execute(
            select(UserWatchlist.ticker).where(UserWatchlist.user_id == uuid.UUID(user_id))
        )
        wl_tickers = {r[0] for r in wl_result.fetchall()}
        results = [r for r in results if r.ticker in wl_tickers]

    return results


@router.get("/tickers/{ticker}/messages")
async def ticker_messages(
    ticker: str,
    request: Request,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(SentimentMessage)
        .where(SentimentMessage.ticker == ticker.upper())
        .order_by(desc(SentimentMessage.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    count_stmt = select(func.count(SentimentMessage.id)).where(
        SentimentMessage.ticker == ticker.upper()
    )
    total = (await session.execute(count_stmt)).scalar() or 0

    messages = [
        SentimentMessageResponse(
            id=str(m.id),
            channel_name=m.channel_name,
            author=m.author,
            content=m.content,
            sentiment_label=m.sentiment_label,
            sentiment_score=float(m.sentiment_score) if m.sentiment_score else None,
            confidence=float(m.confidence) if m.confidence else None,
            message_timestamp=m.message_timestamp.isoformat() if m.message_timestamp else None,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in rows
    ]
    return {"total": total, "messages": messages}


@router.get("/tickers/{ticker}/summary")
async def ticker_summary(
    ticker: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    stmt = (
        select(SentimentMessage)
        .where(
            SentimentMessage.ticker == ticker.upper(),
            SentimentMessage.created_at >= cutoff,
        )
        .order_by(desc(SentimentMessage.created_at))
        .limit(50)
    )
    result = await session.execute(stmt)
    messages = result.scalars().all()

    if not messages:
        return {"ticker": ticker.upper(), "summary": "No recent sentiment data available.", "message_count": 0}

    contents = [m.content for m in messages[:20]]
    summary_input = f"Summarize the market sentiment for {ticker.upper()} based on these messages:\n\n"
    summary_input += "\n".join(f"- {c[:200]}" for c in contents)

    try:
        from shared.llm.client import OllamaClient
        llm = OllamaClient()
        summary = await llm.generate(
            prompt=summary_input,
            system=(
                "You are a financial analyst. Provide a concise"
                " 2-3 sentence summary of market sentiment."
                " Be specific about bullish/bearish signals."
            ),
        )
    except Exception:
        logger.exception("LLM summary failed for %s", ticker)
        bullish = sum(1 for m in messages if m.sentiment_label and "bullish" in m.sentiment_label.lower())
        bearish = sum(1 for m in messages if m.sentiment_label and "bearish" in m.sentiment_label.lower())
        summary = (
            f"{ticker.upper()} has {len(messages)} recent mentions"
            f" with {bullish} bullish and {bearish} bearish signals."
        )

    return {
        "ticker": ticker.upper(),
        "summary": summary,
        "message_count": len(messages),
    }


@router.get("/tickers/{ticker}/history")
async def ticker_history(
    ticker: str,
    windows: int = Query(24, le=100),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(TickerSentiment)
        .where(TickerSentiment.ticker == ticker.upper())
        .order_by(desc(TickerSentiment.period_start))
        .limit(windows)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(),
            "sentiment_label": r.sentiment_label,
            "sentiment_score": float(r.sentiment_score),
            "message_count": r.message_count,
            "bullish_count": r.bullish_count,
            "bearish_count": r.bearish_count,
            "neutral_count": r.neutral_count,
            "mention_change_pct": float(r.mention_change_pct) if r.mention_change_pct else None,
        }
        for r in rows
    ]


@router.get("/alerts")
async def list_alerts(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(SentimentAlert)
        .where(SentimentAlert.user_id == uuid.UUID(user_id))
        .order_by(desc(SentimentAlert.created_at))
    )
    alerts = result.scalars().all()
    return [_alert_response(a) for a in alerts]


@router.post("/alerts", status_code=201)
async def create_alert(
    req: AlertCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    alert = SentimentAlert(
        user_id=uuid.UUID(user_id),
        ticker=req.ticker.upper() if req.ticker else None,
        alert_type=req.alert_type,
        config=req.config,
        enabled=req.enabled,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return _alert_response(alert)


@router.put("/alerts/{alert_id}")
async def update_alert(
    alert_id: str,
    req: AlertCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(SentimentAlert).where(
            SentimentAlert.id == uuid.UUID(alert_id),
            SentimentAlert.user_id == uuid.UUID(user_id),
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.ticker = req.ticker.upper() if req.ticker else None
    alert.alert_type = req.alert_type
    alert.config = req.config
    alert.enabled = req.enabled
    await session.commit()
    await session.refresh(alert)
    return _alert_response(alert)


@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(SentimentAlert).where(
            SentimentAlert.id == uuid.UUID(alert_id),
            SentimentAlert.user_id == uuid.UUID(user_id),
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await session.delete(alert)
    await session.commit()


@router.patch("/alerts/{alert_id}/toggle")
async def toggle_alert(
    alert_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(SentimentAlert).where(
            SentimentAlert.id == uuid.UUID(alert_id),
            SentimentAlert.user_id == uuid.UUID(user_id),
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.enabled = not alert.enabled
    await session.commit()
    await session.refresh(alert)
    return _alert_response(alert)


def _alert_response(a: SentimentAlert) -> AlertResponse:
    return AlertResponse(
        id=str(a.id),
        ticker=a.ticker,
        alert_type=a.alert_type,
        config=a.config or {},
        enabled=a.enabled,
        last_triggered_at=a.last_triggered_at.isoformat() if a.last_triggered_at else None,
        created_at=a.created_at.isoformat(),
    )
