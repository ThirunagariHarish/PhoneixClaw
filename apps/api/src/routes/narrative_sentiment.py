"""
Narrative Sentiment API routes: sentiment feed, fed-watch, social, earnings, analyst-moves.

Phoenix v3 — Sentiment from DB channel messages (FinBERT) + yfinance earnings/recommendations.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.channel_message import ChannelMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/narrative", tags=["narrative-sentiment"])

# Lazy-loaded sentiment classifier (heavy model, load once)
_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        try:
            from shared.nlp.sentiment_classifier import SentimentClassifier
            _classifier = SentimentClassifier()
        except Exception as e:
            logger.error("Failed to load sentiment classifier: %s", e)
    return _classifier


@router.get("/feed")
async def get_feed(
    db: AsyncSession = Depends(get_session),
    hours: int = Query(24, ge=1, le=168),
) -> dict:
    """Sentiment feed from recent Discord channel messages scored with FinBERT."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(ChannelMessage)
        .where(ChannelMessage.posted_at >= since)
        .where(ChannelMessage.message_type.in_(["buy_signal", "sell_signal", "info", "unknown"]))
        .order_by(ChannelMessage.posted_at.desc())
        .limit(100)
    )
    messages = result.scalars().all()

    items = []
    classifier = _get_classifier()

    for msg in messages:
        item = {
            "id": str(msg.id),
            "content": msg.content[:200],
            "author": msg.author,
            "channel": msg.channel,
            "type": msg.message_type,
            "tickers": msg.tickers_mentioned or [],
            "posted_at": msg.posted_at.isoformat(),
        }
        # Score with FinBERT if available
        if classifier:
            try:
                result = classifier.classify(msg.content)
                item["sentiment"] = result.level.value
                item["sentiment_score"] = result.score
                item["confidence"] = result.confidence
            except Exception:
                item["sentiment"] = "unknown"
                item["sentiment_score"] = 0
                item["confidence"] = 0
        items.append(item)

    # Aggregate metrics
    scores = [i.get("sentiment_score", 0) for i in items if "sentiment_score" in i]
    avg_sentiment = round(sum(scores) / len(scores), 3) if scores else 0
    bullish_count = sum(1 for i in items if i.get("sentiment") in ("Bullish", "Very Bullish"))
    bearish_count = sum(1 for i in items if i.get("sentiment") in ("Bearish", "Very Bearish"))
    total = len(items)

    # Fear & Greed: scale from bullish/bearish ratio (0=extreme fear, 100=extreme greed)
    if bullish_count + bearish_count > 0:
        fear_greed = round(bullish_count / (bullish_count + bearish_count) * 100)
    else:
        fear_greed = 50  # neutral when no scored messages

    # Twitter velocity: proxy from message volume (normalized 0-1)
    # 100+ messages/day = 1.0, scale linearly
    twitter_velocity = round(min(total / 100.0, 1.0), 2) if total > 0 else 0

    # Transform items to match frontend expected shape
    feed_items = []
    for item in items[:50]:
        feed_items.append({
            "id": item.get("id", ""),
            "ts": item.get("posted_at", ""),
            "source": item.get("channel", "discord"),
            "headline": item.get("content", ""),
            "score": item.get("sentiment_score", 0),
            "tickers": item.get("tickers", []),
            "urgent": abs(item.get("sentiment_score", 0)) > 0.8,
        })

    return {
        "items": feed_items,
        "metrics": {
            "marketSentiment": avg_sentiment,
            "fearGreed": fear_greed,
            "twitterVelocity": twitter_velocity,
            "newsSentimentAvg": avg_sentiment,
            "bullishCount": bullish_count,
            "bearishCount": bearish_count,
            "totalMessages": total,
        },
    }


@router.get("/fed-watch")
async def get_fed_watch() -> list:
    """Upcoming Fed events from static calendar with frontend-compatible fields."""
    from shared.market.macro import ECONOMIC_CALENDAR_2026
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fed_events = [e for e in ECONOMIC_CALENDAR_2026 if e["date"] >= today and "FOMC" in e["event"]]
    result = []
    for i, e in enumerate(fed_events[:5]):
        is_decision = "Decision" in e["event"]
        result.append({
            "id": f"fed-{i}",
            "name": e["event"],
            "date": e["date"],
            "summary": "Rate decision and press conference" if is_decision else "Two-day meeting begins",
            "hawkish": 0.55 if is_decision else 0.5,
            "dovish": 0.45 if is_decision else 0.5,
        })
    return result


@router.get("/social")
async def get_social(
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Social pulse: top mentioned tickers from Discord channels (last 24h)."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    result = await db.execute(
        select(ChannelMessage)
        .where(ChannelMessage.posted_at >= since)
        .order_by(ChannelMessage.posted_at.desc())
        .limit(500)
    )
    messages = result.scalars().all()

    # Count ticker mentions
    ticker_counts: dict[str, int] = defaultdict(int)
    for msg in messages:
        for ticker in (msg.tickers_mentioned or []):
            ticker_counts[ticker] += 1

    cashtags = [
        f"${t} ({c})"
        for t, c in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    ]

    # Author activity (proxy for momentum)
    author_counts: dict[str, int] = defaultdict(int)
    for msg in messages:
        author_counts[msg.author] += 1

    momentum = [
        f"{a} ({c} msgs)"
        for a, c in sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # Build sentiment heatmap from messages with ticker mentions
    ticker_sentiments: dict[str, list[float]] = defaultdict(list)
    classifier = _get_classifier()
    for msg in messages[:100]:
        if not msg.tickers_mentioned:
            continue
        score = 0.0
        if classifier:
            try:
                result = classifier.classify(msg.content)
                score = result.score
            except Exception:
                pass
        for ticker in msg.tickers_mentioned:
            ticker_sentiments[ticker].append(score)

    heatmap = [
        {"ticker": t, "sentiment": round(sum(scores) / len(scores), 2)}
        for t, scores in sorted(ticker_sentiments.items(), key=lambda x: len(x[1]), reverse=True)[:15]
        if scores
    ]

    return {"cashtags": cashtags, "wsbMomentum": momentum, "heatmap": heatmap}


@router.get("/earnings")
async def get_earnings(tickers: str = Query("AAPL,MSFT,GOOGL,AMZN,NVDA,TSLA,META")) -> list:
    """Upcoming earnings dates from yfinance."""
    earnings = []
    try:
        import yfinance as yf
        for ticker_str in tickers.split(",")[:15]:
            ticker_str = ticker_str.strip().upper()
            if not ticker_str:
                continue
            try:
                t = yf.Ticker(ticker_str)
                cal = t.calendar
                if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                    # calendar can be a dict or DataFrame
                    if isinstance(cal, dict):
                        earnings_date = cal.get("Earnings Date")
                        if isinstance(earnings_date, list) and earnings_date:
                            earnings_date = str(earnings_date[0])
                        else:
                            earnings_date = str(earnings_date) if earnings_date else None
                        earnings.append({
                            "ticker": ticker_str,
                            "date": earnings_date,
                            "expectation": 0.65,
                            "postRisk": None,
                            "earnings_date": earnings_date,
                            "revenue_estimate": cal.get("Revenue Estimate"),
                            "eps_estimate": cal.get("EPS Estimate"),
                        })
                    else:
                        # DataFrame format
                        ed = str(cal.iloc[0, 0]) if len(cal) > 0 else None
                        earnings.append({
                            "ticker": ticker_str,
                            "date": ed,
                            "expectation": 0.65,
                            "postRisk": None,
                            "earnings_date": ed,
                        })
            except Exception as e:
                logger.debug("Failed to fetch earnings for %s: %s", ticker_str, e)
    except ImportError:
        logger.error("yfinance not installed")
    return earnings


@router.get("/analyst-moves")
async def get_analyst_moves(tickers: str = Query("AAPL,MSFT,GOOGL,AMZN,NVDA,TSLA,META")) -> list:
    """Recent analyst recommendations from yfinance."""
    moves = []
    try:
        import yfinance as yf
        for ticker_str in tickers.split(",")[:15]:
            ticker_str = ticker_str.strip().upper()
            if not ticker_str:
                continue
            try:
                t = yf.Ticker(ticker_str)
                recs = t.recommendations
                if recs is not None and not recs.empty:
                    recent = recs.tail(5)
                    for _, row in recent.iterrows():
                        to_grade = row.get("To Grade", "")
                        from_grade = row.get("From Grade", "")
                        action = row.get("Action", "")
                        # Determine impact direction from action/grade change
                        positive_actions = ("upgrade", "buy", "outperform", "overweight", "strong buy")
                        negative_actions = ("downgrade", "sell", "underperform", "underweight")
                        action_lower = (action or "").lower()
                        to_lower = (to_grade or "").lower()
                        is_positive = (
                            any(a in action_lower for a in positive_actions)
                            or any(a in to_lower for a in positive_actions)
                        )
                        is_negative = (
                            any(a in action_lower for a in negative_actions)
                            or any(a in to_lower for a in negative_actions)
                        )
                        if is_positive:
                            impact = "+Positive"
                        elif is_negative:
                            impact = "-Negative"
                        else:
                            impact = "Neutral"
                        moves.append({
                            "ticker": ticker_str,
                            "firm": row.get("Firm", "Unknown"),
                            "action": (
                                f"{action}: {from_grade} -> {to_grade}"
                                if from_grade else f"{action}: {to_grade}"
                            ),
                            "target": 0,
                            "impact": impact,
                            "to_grade": to_grade,
                            "from_grade": from_grade,
                        })
            except Exception as e:
                logger.debug("Failed to fetch recommendations for %s: %s", ticker_str, e)
    except ImportError:
        logger.error("yfinance not installed")
    return moves
