import asyncio
import logging
import uuid
from datetime import datetime

import msgpack

from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import async_session_factory
from shared.models.trade import SentimentMessage
from shared.nlp.sentiment_classifier import SentimentClassifier
from shared.nlp.ticker_extractor import TickerExtractor

from .aggregator import update_ticker_aggregate
from .alert_evaluator import evaluate_alerts
from .spam_filter import should_filter

logger = logging.getLogger(__name__)

_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            from shared.config.base_config import config
            _redis_client = aioredis.from_url(config.redis.url, decode_responses=True)
            await _redis_client.ping()
        except Exception:
            logger.warning("Redis unavailable for spam dedup")
            _redis_client = False
    return _redis_client if _redis_client is not False else None


class SentimentAnalyzerService:
    def __init__(self):
        self._consumer = KafkaConsumerWrapper(
            topic="raw-sentiment-messages",
            group_id="sentiment-analyzer-group",
        )
        self._producer = KafkaProducerWrapper()
        self._classifier = SentimentClassifier()
        self._extractor = TickerExtractor()
        self._running = False

    async def start(self):
        await self._consumer.start()
        await self._producer.start()
        logger.info("Sentiment analyzer consumer + producer started")

    async def stop(self):
        self._running = False
        await self._consumer.stop()
        await self._producer.stop()

    async def run(self):
        self._running = True
        logger.info("Sentiment analyzer consuming from raw-sentiment-messages")

        async def _handle(value: dict, headers: dict):
            await self._process_message(value)

        await self._consumer.consume(_handle)

    async def _process_message(self, msg: dict):
        redis = await _get_redis()
        if await should_filter(msg, redis):
            return

        content = msg.get("content", "")
        tickers = self._extractor.extract(content)
        if not tickers:
            return

        result = await asyncio.to_thread(self._classifier.classify, content)
        sentiment_label = result["label"]
        sentiment_score = result["score"]
        confidence = result["confidence"]

        user_id = msg.get("user_id")
        if not user_id:
            return

        async with async_session_factory() as session:
            for ticker in tickers:
                sm = SentimentMessage(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id),
                    data_source_id=uuid.UUID(msg["data_source_id"]) if msg.get("data_source_id") else None,
                    channel_name=msg.get("channel_name"),
                    author=msg.get("author"),
                    content=content,
                    ticker=ticker,
                    sentiment_label=sentiment_label,
                    sentiment_score=sentiment_score,
                    confidence=confidence,
                    source_message_id=msg.get("source_message_id"),
                    raw_metadata=msg.get("raw_metadata", {}),
                    message_timestamp=(
                        datetime.fromisoformat(msg["message_timestamp"])
                        if msg.get("message_timestamp")
                        else None
                    ),
                )
                session.add(sm)

                aggregate = await update_ticker_aggregate(
                    session, ticker, sentiment_label, sentiment_score,
                )

                if aggregate:
                    signal = {
                        **aggregate,
                        "user_id": user_id,
                        "trigger": "sentiment",
                    }
                    try:
                        await self._producer.send(
                            "sentiment-signals",
                            msgpack.packb(signal),
                        )
                    except Exception:
                        logger.exception("Failed to emit sentiment signal for %s", ticker)

                    await evaluate_alerts(session, ticker, aggregate, self._producer)

            await session.commit()
            logger.info(
                "Processed sentiment: tickers=%s label=%s score=%.3f",
                tickers, sentiment_label, sentiment_score,
            )
