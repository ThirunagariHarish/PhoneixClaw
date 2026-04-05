"""
Trend Agent backtesting pipeline — analyzes historical headlines to predict
option profitability and build a headline trustworthiness scoring model.

Flow:
1. Pull 2 years of headlines from connected sources (Reddit, Twitter, News, UW)
2. For each headline: extract ticker, determine bullish/bearish sentiment
3. Look up option chain at that timestamp
4. Select a predicted option (call for bullish, put for bearish)
5. Check if option was profitable within a time window
6. Build trustworthiness scoring model
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.agent import Agent, AgentBacktest
from shared.db.models.connector import Connector, ConnectorAgent
from shared.db.models.channel_message import ChannelMessage
from shared.db.models.backtest_trade import BacktestTrade
from shared.nlp.ticker_extractor import TickerExtractor

logger = logging.getLogger(__name__)

_extractor = TickerExtractor()

# Simple keyword-based sentiment (would be LLM in production)
BULLISH_KEYWORDS = [
    "beat", "beats", "exceeds", "upgraded", "upgrade", "bullish", "surge",
    "soars", "rally", "record high", "breakout", "positive", "strong",
    "growth", "profit", "revenue up", "outperform", "buy", "long",
    "double", "triple", "moon", "rocket", "squeeze", "gamma",
]
BEARISH_KEYWORDS = [
    "miss", "misses", "downgrade", "downgraded", "bearish", "plunge",
    "crash", "decline", "fall", "drops", "negative", "weak", "loss",
    "revenue down", "underperform", "sell", "short", "cut", "warning",
    "recall", "lawsuit", "investigation", "bankruptcy", "layoff",
]


def _simple_sentiment(text: str) -> tuple[str, float]:
    """Return (bullish|bearish|neutral, confidence)."""
    lower = text.lower()
    bull_score = sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
    bear_score = sum(1 for kw in BEARISH_KEYWORDS if kw in lower)

    if bull_score > bear_score:
        confidence = min(0.9, 0.3 + bull_score * 0.15)
        return "bullish", confidence
    elif bear_score > bull_score:
        confidence = min(0.9, 0.3 + bear_score * 0.15)
        return "bearish", confidence
    return "neutral", 0.2


def _simulate_option_outcome(
    sentiment: str,
    ticker: str,
    posted_at: datetime,
) -> Optional[dict]:
    """
    Look up real option chain and historical price to determine profitability.
    Requires Unusual Whales or equivalent market data integration.
    Returns None until real market data provider is wired in.
    """
    raise NotImplementedError(
        "_simulate_option_outcome requires a real options data provider "
        "(e.g. Unusual Whales historical chain). Random simulation removed."
    )


async def run_trend_backtest(
    session: AsyncSession,
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    progress_callback=None,
) -> dict:
    """
    Full Trend Agent backtest pipeline.
    """
    agent = await session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    links = (await session.execute(
        select(ConnectorAgent).where(ConnectorAgent.agent_id == agent_id)
    )).scalars().all()

    if not links:
        return {"error": "No connectors linked to agent"}

    if progress_callback:
        await progress_callback("loading_headlines", 5)

    # Load all messages from connected sources
    messages = (await session.execute(
        select(ChannelMessage)
        .where(ChannelMessage.connector_id.in_([l.connector_id for l in links]))
        .order_by(ChannelMessage.posted_at.asc())
    )).scalars().all()

    if progress_callback:
        await progress_callback("analyzing_sentiment", 20)

    # Analyze each headline
    headline_analyses = []
    source_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "profitable": 0, "tickers": set()})

    for msg in messages:
        tickers = _extractor.extract(msg.content)
        if not tickers:
            continue

        primary_ticker = tickers[0]
        sentiment, confidence = _simple_sentiment(msg.content)
        if sentiment == "neutral":
            continue

        try:
            option_result = _simulate_option_outcome(sentiment, primary_ticker, msg.posted_at)
        except NotImplementedError:
            continue
        if option_result is None:
            continue

        headline_analyses.append({
            "message_id": str(msg.id),
            "channel": msg.channel,
            "author": msg.author,
            "content": msg.content[:200],
            "ticker": primary_ticker,
            "sentiment": sentiment,
            "sentiment_confidence": confidence,
            "posted_at": msg.posted_at,
            **option_result,
        })

        source_stats[msg.channel]["total"] += 1
        source_stats[msg.channel]["tickers"].add(primary_ticker)
        if option_result["is_profitable"]:
            source_stats[msg.channel]["profitable"] += 1

    if progress_callback:
        await progress_callback("building_trades", 50)

    # Create BacktestTrade records
    trades: list[BacktestTrade] = []
    for analysis in headline_analyses:
        entry_time = analysis["posted_at"]
        exit_time = entry_time + timedelta(days=analysis.get("dte", 14))

        trade = BacktestTrade(
            id=uuid.uuid4(),
            backtest_id=backtest_id,
            agent_id=agent_id,
            ticker=analysis["ticker"],
            side="long" if analysis["sentiment"] == "bullish" else "short",
            entry_price=analysis["premium"],
            exit_price=analysis["premium"] * (1 + analysis["option_return_pct"] / 100),
            entry_time=entry_time,
            exit_time=exit_time,
            pnl=analysis["premium"] * analysis["option_return_pct"] / 100,
            pnl_pct=analysis["option_return_pct"],
            holding_period_hours=(exit_time - entry_time).total_seconds() / 3600,
            signal_message_id=uuid.UUID(analysis["message_id"]),
            is_profitable=analysis["is_profitable"],
            hour_of_day=entry_time.hour,
            day_of_week=entry_time.weekday(),
            pattern_tags=[analysis["sentiment"], analysis["option_type"].lower()],
        )
        session.add(trade)
        trades.append(trade)

    if progress_callback:
        await progress_callback("scoring_sources", 70)

    # Build headline trustworthiness model
    source_scores = {}
    for source, stats in source_stats.items():
        total = stats["total"]
        profitable = stats["profitable"]
        wr = profitable / total if total > 0 else 0
        source_scores[source] = {
            "total_headlines": total,
            "profitable_predictions": profitable,
            "accuracy": round(wr, 4),
            "unique_tickers": len(stats["tickers"]),
            "trustworthiness": round(min(1.0, wr * (min(total, 50) / 50)), 4),
        }

    # Sentiment accuracy by type
    bullish_trades = [a for a in headline_analyses if a["sentiment"] == "bullish"]
    bearish_trades = [a for a in headline_analyses if a["sentiment"] == "bearish"]
    sentiment_accuracy = {
        "bullish": {
            "total": len(bullish_trades),
            "profitable": sum(1 for a in bullish_trades if a["is_profitable"]),
            "accuracy": round(sum(1 for a in bullish_trades if a["is_profitable"]) / max(len(bullish_trades), 1), 4),
        },
        "bearish": {
            "total": len(bearish_trades),
            "profitable": sum(1 for a in bearish_trades if a["is_profitable"]),
            "accuracy": round(sum(1 for a in bearish_trades if a["is_profitable"]) / max(len(bearish_trades), 1), 4),
        },
    }

    if progress_callback:
        await progress_callback("computing_metrics", 85)

    # Compute overall metrics
    total_count = len(trades)
    profitable_count = sum(1 for t in trades if t.is_profitable)
    win_rate = profitable_count / total_count if total_count > 0 else 0
    total_return = sum(t.pnl_pct for t in trades)

    pnls = [t.pnl_pct for t in trades]
    if len(pnls) > 1:
        avg_ret = total_return / len(pnls)
        std_ret = (sum((r - avg_ret) ** 2 for r in pnls) / len(pnls)) ** 0.5
        sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0
    else:
        sharpe = 0

    # Equity curve
    equity_curve = []
    eq = 100000
    for i, p in enumerate(pnls):
        eq *= (1 + p / 100)
        equity_curve.append({"day": i, "equity": round(eq, 2)})

    peak = 0
    max_dd = 0
    cum = 0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    # Intelligence rules for trend agents
    rules = []
    for source, score in source_scores.items():
        if score["total_headlines"] >= 5:
            rules.append({
                "name": f"source_{source.replace('/', '_').replace(' ', '_')}",
                "condition": f"source == '{source}'",
                "description": f"Headlines from {source}",
                "win_rate": score["accuracy"],
                "sample_size": score["total_headlines"],
                "weight": round((score["trustworthiness"] - 0.5) * 2, 3),
            })

    if sentiment_accuracy["bullish"]["total"] >= 5:
        rules.append({
            "name": "bullish_sentiment",
            "condition": "sentiment == 'bullish'",
            "description": "Bullish sentiment predictions",
            "win_rate": sentiment_accuracy["bullish"]["accuracy"],
            "sample_size": sentiment_accuracy["bullish"]["total"],
            "weight": round((sentiment_accuracy["bullish"]["accuracy"] - 0.5) * 2, 3),
        })
    if sentiment_accuracy["bearish"]["total"] >= 5:
        rules.append({
            "name": "bearish_sentiment",
            "condition": "sentiment == 'bearish'",
            "description": "Bearish sentiment predictions",
            "win_rate": sentiment_accuracy["bearish"]["accuracy"],
            "sample_size": sentiment_accuracy["bearish"]["total"],
            "weight": round((sentiment_accuracy["bearish"]["accuracy"] - 0.5) * 2, 3),
        })

    rules.sort(key=lambda r: abs(r["weight"]), reverse=True)

    # Update backtest
    backtest = await session.get(AgentBacktest, backtest_id)
    if backtest:
        backtest.status = "COMPLETED"
        backtest.total_trades = total_count
        backtest.win_rate = round(win_rate, 4)
        backtest.total_return = round(total_return, 2)
        backtest.sharpe_ratio = round(sharpe, 2)
        backtest.max_drawdown = round(max_dd, 2)
        backtest.equity_curve = equity_curve
        backtest.metrics = {
            "rules": rules,
            "source_scores": source_scores,
            "sentiment_accuracy": sentiment_accuracy,
            "overall_channel_metrics": {
                "total_headlines_analyzed": len(messages),
                "actionable_headlines": len(headline_analyses),
                "total_trades_identified": total_count,
                "profitable_trades": profitable_count,
                "overall_win_rate": round(win_rate, 4),
                "avg_win_pct": round(
                    sum(t.pnl_pct for t in trades if t.is_profitable) / max(profitable_count, 1), 2
                ),
                "avg_loss_pct": round(
                    sum(t.pnl_pct for t in trades if not t.is_profitable) / max(total_count - profitable_count, 1), 2
                ),
                "best_source": max(source_scores, key=lambda s: source_scores[s]["trustworthiness"]) if source_scores else None,
                "rules_count": len(rules),
            },
        }
        backtest.completed_at = datetime.now(timezone.utc)

    if agent:
        agent.status = "BACKTEST_COMPLETE"

    await session.commit()

    if progress_callback:
        await progress_callback("complete", 100)

    return {
        "total_trades": total_count,
        "win_rate": win_rate,
        "total_return": total_return,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "rules_discovered": len(rules),
        "sources_analyzed": len(source_scores),
    }
