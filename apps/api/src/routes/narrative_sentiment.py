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


@router.get("/sentiment-heatmap")
async def get_sentiment_heatmap(
    db: AsyncSession = Depends(get_session),
    hours: int = Query(24, ge=1, le=168),
) -> dict:
    """Per-ticker sentiment scores for color-coded heatmap grid."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(ChannelMessage)
        .where(ChannelMessage.posted_at >= since)
        .order_by(ChannelMessage.posted_at.desc())
        .limit(500)
    )
    messages = result.scalars().all()

    classifier = _get_classifier()
    ticker_sentiments: dict[str, list[float]] = defaultdict(list)

    for msg in messages:
        if not msg.tickers_mentioned:
            continue
        score = 0.0
        if classifier:
            try:
                res = classifier.classify(msg.content)
                score = res.score
            except Exception:
                pass
        for ticker in msg.tickers_mentioned:
            ticker_sentiments[ticker].append(score)

    heatmap = []
    for ticker, scores_list in sorted(ticker_sentiments.items(), key=lambda x: len(x[1]), reverse=True)[:30]:
        if not scores_list:
            continue
        avg = sum(scores_list) / len(scores_list)
        bullish_pct = round(sum(1 for s in scores_list if s > 0.2) / len(scores_list) * 100, 1)
        bearish_pct = round(sum(1 for s in scores_list if s < -0.2) / len(scores_list) * 100, 1)
        heatmap.append({
            "ticker": ticker,
            "sentiment": round(avg, 3),
            "mentions": len(scores_list),
            "bullishPct": bullish_pct,
            "bearishPct": bearish_pct,
            "label": "Bullish" if avg > 0.2 else ("Bearish" if avg < -0.2 else "Neutral"),
        })

    return {"heatmap": heatmap}


@router.get("/fear-greed")
async def get_fear_greed():
    """Composite Fear & Greed index from VIX + put/call + breadth + momentum."""
    components = {}
    total_score = 50  # default neutral

    try:
        import yfinance as yf

        # VIX component (0-100: low VIX = greed, high VIX = fear)
        try:
            vix_data = yf.download("^VIX", period="5d", interval="1d", progress=False)
            if not vix_data.empty:
                vix = float(vix_data["Close"].iloc[-1])
                # VIX 10 = extreme greed (100), VIX 40 = extreme fear (0)
                vix_score = max(0, min(100, round((40 - vix) / 30 * 100)))
                components["vix"] = {"value": round(vix, 2), "score": vix_score, "label": "Volatility (VIX)"}
            else:
                vix_score = 50
                components["vix"] = {"value": None, "score": 50, "label": "Volatility (VIX)"}
        except Exception:
            vix_score = 50
            components["vix"] = {"value": None, "score": 50, "label": "Volatility (VIX)"}

        # SPY momentum (above/below 20-day SMA)
        try:
            spy_data = yf.download("SPY", period="30d", interval="1d", progress=False)
            if not spy_data.empty and len(spy_data) >= 20:
                spy_close = spy_data["Close"].squeeze()
                current = float(spy_close.iloc[-1])
                sma20 = float(spy_close.rolling(20).mean().iloc[-1])
                pct_above = (current - sma20) / sma20 * 100
                momentum_score = max(0, min(100, round(50 + pct_above * 10)))
                components["momentum"] = {
                    "value": round(pct_above, 2), "score": momentum_score, "label": "Market Momentum",
                }
            else:
                momentum_score = 50
                components["momentum"] = {"value": None, "score": 50, "label": "Market Momentum"}
        except Exception:
            momentum_score = 50
            components["momentum"] = {"value": None, "score": 50, "label": "Market Momentum"}

        # Market breadth (advance/decline proxy: IWM vs SPY relative)
        try:
            breadth_data = yf.download("IWM SPY", period="5d", interval="1d", progress=False)
            if not breadth_data.empty:
                try:
                    iwm = breadth_data["Close"]["IWM"].dropna()
                    spy = breadth_data["Close"]["SPY"].dropna()
                    if len(iwm) >= 2 and len(spy) >= 2:
                        iwm_ret = (float(iwm.iloc[-1]) - float(iwm.iloc[-2])) / float(iwm.iloc[-2]) * 100
                        spy_ret = (float(spy.iloc[-1]) - float(spy.iloc[-2])) / float(spy.iloc[-2]) * 100
                        breadth_diff = iwm_ret - spy_ret
                        breadth_score = max(0, min(100, round(50 + breadth_diff * 20)))
                    else:
                        breadth_score = 50
                except Exception:
                    breadth_score = 50
                components["breadth"] = {"value": None, "score": breadth_score, "label": "Market Breadth"}
            else:
                breadth_score = 50
                components["breadth"] = {"value": None, "score": 50, "label": "Market Breadth"}
        except Exception:
            breadth_score = 50
            components["breadth"] = {"value": None, "score": 50, "label": "Market Breadth"}

        # Safe haven demand (TLT strength = fear, TLT weakness = greed)
        try:
            tlt_data = yf.download("TLT", period="5d", interval="1d", progress=False)
            if not tlt_data.empty and len(tlt_data) >= 2:
                tlt_close = tlt_data["Close"].squeeze()
                tlt_ret = (float(tlt_close.iloc[-1]) - float(tlt_close.iloc[-2])) / float(tlt_close.iloc[-2]) * 100
                # TLT up = flight to safety = fear
                safe_haven_score = max(0, min(100, round(50 - tlt_ret * 20)))
                components["safeHaven"] = {
                    "value": round(tlt_ret, 2), "score": safe_haven_score, "label": "Safe Haven Demand",
                }
            else:
                safe_haven_score = 50
                components["safeHaven"] = {"value": None, "score": 50, "label": "Safe Haven Demand"}
        except Exception:
            safe_haven_score = 50
            components["safeHaven"] = {"value": None, "score": 50, "label": "Safe Haven Demand"}

        # Compute composite
        comp_scores = [c["score"] for c in components.values()]
        total_score = round(sum(comp_scores) / len(comp_scores)) if comp_scores else 50

    except ImportError:
        logger.error("yfinance not installed")
    except Exception as e:
        logger.error("Failed to compute Fear & Greed: %s", e)

    # Determine label
    if total_score >= 80:
        label = "Extreme Greed"
    elif total_score >= 60:
        label = "Greed"
    elif total_score >= 40:
        label = "Neutral"
    elif total_score >= 20:
        label = "Fear"
    else:
        label = "Extreme Fear"

    return {
        "score": total_score,
        "label": label,
        "components": components,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/sentiment-timeseries")
async def get_sentiment_timeseries(
    db: AsyncSession = Depends(get_session),
    days: int = Query(7, ge=1, le=30),
) -> dict:
    """Aggregate sentiment over time for line chart."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(ChannelMessage)
        .where(ChannelMessage.posted_at >= since)
        .order_by(ChannelMessage.posted_at.asc())
        .limit(2000)
    )
    messages = result.scalars().all()

    classifier = _get_classifier()

    # Group by date
    daily_scores: dict[str, list[float]] = defaultdict(list)
    for msg in messages:
        date_key = msg.posted_at.strftime("%Y-%m-%d")
        score = 0.0
        if classifier:
            try:
                res = classifier.classify(msg.content)
                score = res.score
            except Exception:
                pass
        daily_scores[date_key].append(score)

    timeseries = []
    for date_key in sorted(daily_scores.keys()):
        scores_list = daily_scores[date_key]
        avg = sum(scores_list) / len(scores_list) if scores_list else 0
        timeseries.append({
            "date": date_key,
            "sentiment": round(avg, 3),
            "count": len(scores_list),
            "bullish": sum(1 for s in scores_list if s > 0.2),
            "bearish": sum(1 for s in scores_list if s < -0.2),
        })

    return {"timeseries": timeseries, "days": days}


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


@router.get("/earnings-history")
async def get_earnings_history(tickers: str = Query("AAPL,MSFT,GOOGL,AMZN,NVDA")) -> list:
    """Historical EPS beat/miss data from yfinance for earnings intelligence tab."""
    history = []
    try:
        import yfinance as yf
        for ticker_str in tickers.split(",")[:10]:
            ticker_str = ticker_str.strip().upper()
            if not ticker_str:
                continue
            try:
                t = yf.Ticker(ticker_str)
                # earnings_history gives historical EPS surprise
                eh = t.earnings_history
                if eh is not None and not eh.empty:
                    for _, row in eh.iterrows():
                        try:
                            eps_est = row.get("epsEstimate")
                            eps_act = row.get("epsActual")
                            surprise = row.get("surprisePercent") or row.get("epsSurprisePct")
                            date_val = row.get("quarterEnd") or row.name
                            date_str = str(date_val)[:10] if date_val is not None else None

                            # NaN-safe
                            eps_est_f = float(eps_est) if eps_est is not None and eps_est == eps_est else None
                            eps_act_f = float(eps_act) if eps_act is not None and eps_act == eps_act else None
                            surprise_f = float(surprise) if surprise is not None and surprise == surprise else None

                            if eps_act_f is not None and eps_est_f is not None and surprise_f is None:
                                if eps_est_f != 0:
                                    surprise_f = round((eps_act_f - eps_est_f) / abs(eps_est_f) * 100, 2)

                            beat_miss = "Beat" if (surprise_f is not None and surprise_f > 0) else (
                                "Miss" if (surprise_f is not None and surprise_f < 0) else "In-line"
                            )

                            history.append({
                                "ticker": ticker_str,
                                "date": date_str,
                                "epsEstimate": eps_est_f,
                                "epsActual": eps_act_f,
                                "surprisePct": surprise_f,
                                "result": beat_miss,
                            })
                        except Exception:
                            continue
            except Exception as e:
                logger.debug("Failed to fetch earnings history for %s: %s", ticker_str, e)
    except ImportError:
        logger.error("yfinance not installed")
    return history


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
