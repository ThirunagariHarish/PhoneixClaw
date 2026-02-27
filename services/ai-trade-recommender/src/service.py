import asyncio
import logging
import uuid

import httpx
import msgpack

from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.market.calendar import MarketCalendar, MarketHoursMode
from shared.models.database import async_session_factory
from shared.models.trade import AITradeDecision

logger = logging.getLogger(__name__)

_redis_client = None
DEDUP_TTL = 1800
OPTION_CHAIN_ANALYZER_URL = "http://option-chain-analyzer:8024"


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            from shared.config.base_config import config
            _redis_client = aioredis.from_url(config.redis.url, decode_responses=True)
            await _redis_client.ping()
        except Exception:
            logger.warning("Redis unavailable for AI dedup")
            _redis_client = False
    return _redis_client if _redis_client is not False else None


class AITradeRecommenderService:
    def __init__(self):
        self._sentiment_consumer = KafkaConsumerWrapper(
            topic="sentiment-signals",
            group_id="ai-trade-recommender-sentiment",
        )
        self._news_consumer = KafkaConsumerWrapper(
            topic="news-signals",
            group_id="ai-trade-recommender-news",
        )
        self._producer = KafkaProducerWrapper()
        self._calendar = MarketCalendar()
        self._running = False

    async def start(self):
        await self._sentiment_consumer.start()
        await self._news_consumer.start()
        await self._producer.start()
        logger.info("AI Trade Recommender started")

    async def stop(self):
        self._running = False
        await self._sentiment_consumer.stop()
        await self._news_consumer.stop()
        await self._producer.stop()

    async def run(self):
        self._running = True
        sentiment_task = asyncio.create_task(self._consume_signals(self._sentiment_consumer, "sentiment"))
        news_task = asyncio.create_task(self._consume_signals(self._news_consumer, "news"))
        await asyncio.gather(sentiment_task, news_task)

    async def _consume_signals(self, consumer: KafkaConsumerWrapper, trigger_type: str):
        logger.info("Consuming %s signals", trigger_type)
        async for raw in consumer.consume():
            if not self._running:
                break
            try:
                signal = msgpack.unpackb(raw, raw=False)
                await self._process_signal(signal, trigger_type)
            except Exception:
                logger.exception("Error processing %s signal", trigger_type)

    async def _process_signal(self, signal: dict, trigger_type: str):
        mode = MarketHoursMode(signal.get("market_hours_mode", "extended"))
        if not self._calendar.should_trade(mode):
            logger.debug("Market closed (mode=%s), skipping signal", mode.value)
            return

        tickers = signal.get("tickers") if trigger_type == "news" else [signal.get("ticker")]
        tickers = [t for t in (tickers or []) if t]
        if not tickers:
            return

        for ticker in tickers:
            direction = self._determine_direction(signal, trigger_type)

            redis = await _get_redis()
            dedup_key = f"ai_trade:{ticker}:{direction}"
            if redis:
                try:
                    if await redis.get(dedup_key):
                        logger.debug("Dedup: skipping %s %s", ticker, direction)
                        continue
                except Exception:
                    pass

            analysis = await self._call_option_analyzer(ticker, direction, signal)

            decision_data = {
                "ticker": ticker,
                "direction": direction,
                "trigger_type": trigger_type,
                "trigger_data": signal,
                "analysis": analysis,
            }

            if analysis and analysis.get("contracts"):
                top_contract = analysis["contracts"][0]
                trade_msg = {
                    "ticker": ticker,
                    "action": "BTO",
                    "asset_type": "option",
                    "contract_type": top_contract.get("option_type", "call"),
                    "strike": top_contract.get("strike"),
                    "expiration": top_contract.get("expiration"),
                    "quantity": 1,
                    "source": f"ai-{trigger_type}",
                    "ai_analysis_id": analysis.get("analysis_id"),
                    "rationale": analysis.get("rationale"),
                    "user_id": signal.get("user_id"),
                }
                try:
                    await self._producer.send("parsed-trades", msgpack.packb(trade_msg))
                    decision_data["decision"] = "executed"
                    decision_data["trade_params"] = trade_msg
                    if redis:
                        try:
                            await redis.setex(dedup_key, DEDUP_TTL, "1")
                        except Exception:
                            pass
                except Exception:
                    logger.exception("Failed to publish trade for %s", ticker)
                    decision_data["decision"] = "error"
            else:
                decision_data["decision"] = "skipped"
                decision_data["decision_rationale"] = "No suitable contracts found"

            await self._log_decision(decision_data, signal.get("user_id"))

    def _determine_direction(self, signal: dict, trigger_type: str) -> str:
        if trigger_type == "sentiment":
            label = signal.get("sentiment_label", "").lower()
            if "very bullish" in label:
                return "very_bullish"
            if "bullish" in label:
                return "bullish"
            if "very bearish" in label:
                return "very_bearish"
            if "bearish" in label:
                return "bearish"
            return "neutral"
        else:
            label = signal.get("sentiment_label", "").lower()
            if "positive" in label or "bullish" in label:
                return "bullish"
            if "negative" in label or "bearish" in label:
                return "bearish"
            return "neutral"

    async def _call_option_analyzer(self, ticker: str, direction: str, context: dict) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{OPTION_CHAIN_ANALYZER_URL}/analyze",
                    json={"ticker": ticker, "direction": direction, "context": context},
                )
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("Option analyzer returned %d", resp.status_code)
        except Exception:
            logger.warning("Option chain analyzer unavailable for %s", ticker)
        return None

    async def _log_decision(self, data: dict, user_id: str | None):
        try:
            async with async_session_factory() as session:
                log = AITradeDecision(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id) if user_id else None,
                    trigger_type=data.get("trigger_type", "unknown"),
                    trigger_data=data.get("trigger_data", {}),
                    ticker=data.get("ticker"),
                    decision=data.get("decision", "unknown"),
                    decision_rationale=data.get("decision_rationale"),
                    trade_params=data.get("trade_params"),
                    option_analysis_id=(
                        uuid.UUID(data["analysis"]["analysis_id"])
                        if (data.get("analysis") or {}).get("analysis_id")
                        else None
                    ),
                )
                session.add(log)
                await session.commit()
        except Exception:
            logger.exception("Failed to log AI decision")
