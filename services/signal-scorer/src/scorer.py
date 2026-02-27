import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func

from shared.config.base_config import config
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import AnalystPerformance, TickerSentiment
from shared.market.calendar import MarketCalendar

logger = logging.getLogger(__name__)


class SignalScorerService:
    def __init__(self):
        self.consumer = KafkaConsumerWrapper("parsed-trades", "signal-scorer-group")
        self.producer = KafkaProducerWrapper()
        self.calendar = MarketCalendar()
        self._last_breakdown = {}

    async def start(self):
        await self.producer.start()
        await self.consumer.start()
        logger.info("Signal scorer started")

    async def stop(self):
        await self.consumer.stop()
        await self.producer.stop()

    async def run(self):
        await self.consumer.consume(self._handle_signal)

    async def _handle_signal(self, signal: dict):
        try:
            score = await self._compute_score(signal)
            signal["confidence_score"] = score
            signal["scored_at"] = datetime.now(timezone.utc).isoformat()
            signal["score_breakdown"] = self._last_breakdown
            await self.producer.send("scored-trades", signal)
            logger.info(
                "Signal scored: %s %s %s -> %d/100",
                signal.get("action"), signal.get("ticker"), signal.get("strike"), score
            )
        except Exception:
            logger.exception("Failed to score signal %s", signal.get("trade_id"))
            signal["confidence_score"] = 50
            signal["scored_at"] = datetime.now(timezone.utc).isoformat()
            await self.producer.send("scored-trades", signal)

    async def _compute_score(self, signal: dict) -> int:
        breakdown = {}

        analyst_score = await self._score_analyst(signal.get("source_author", ""))
        breakdown["analyst"] = analyst_score

        sentiment_score = await self._score_sentiment(
            signal.get("ticker", ""), signal.get("action", "BUY")
        )
        breakdown["sentiment"] = sentiment_score

        market_score = self._score_market_conditions()
        breakdown["market"] = market_score

        quality_score = self._score_signal_quality(signal)
        breakdown["quality"] = quality_score

        self._last_breakdown = breakdown
        total = analyst_score + sentiment_score + market_score + quality_score
        return max(0, min(100, total))

    async def _score_analyst(self, author: str) -> int:
        if not author:
            return 10
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AnalystPerformance)
                    .where(AnalystPerformance.author == author)
                    .order_by(AnalystPerformance.period_end.desc())
                    .limit(1)
                )
                perf = result.scalar_one_or_none()
                if not perf:
                    return 10

                win_rate = float(perf.win_rate or 0)
                win_points = min(15, win_rate * 15)

                total_pnl = float(perf.total_pnl or 0)
                pf_points = min(15, 7.5 + (5 if total_pnl > 0 else -2.5) + min(5, total_pnl / 1000))

                return int(win_points + pf_points)
        except Exception:
            logger.debug("Analyst score lookup failed for %s", author)
            return 10

    async def _score_sentiment(self, ticker: str, action: str) -> int:
        if not ticker:
            return 10
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(TickerSentiment)
                    .where(TickerSentiment.ticker == ticker.upper())
                    .order_by(TickerSentiment.period_end.desc())
                    .limit(1)
                )
                sentiment = result.scalar_one_or_none()
                if not sentiment:
                    return 10

                score_val = float(sentiment.sentiment_score or 0)
                is_buy = action.upper() in ("BUY", "BTO")

                if is_buy and score_val > 0.3:
                    return 20
                elif is_buy and score_val < -0.3:
                    return 5
                elif not is_buy and score_val < -0.3:
                    return 18
                elif not is_buy and score_val > 0.3:
                    return 5
                return 10
        except Exception:
            logger.debug("Sentiment score lookup failed for %s", ticker)
            return 10

    def _score_market_conditions(self) -> int:
        try:
            if self.calendar.is_market_open():
                return 18
            return 8
        except Exception:
            return 12

    def _score_signal_quality(self, signal: dict) -> int:
        score = 0
        if signal.get("price") and float(signal.get("price", 0)) > 0:
            score += 8
        if signal.get("expiration"):
            score += 7
        if signal.get("strike") and float(signal.get("strike", 0)) > 0:
            score += 5
        if signal.get("quantity"):
            score += 5
        if signal.get("profit_target") or signal.get("stop_loss"):
            score += 5
        return min(30, score)
