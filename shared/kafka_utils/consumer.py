from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import msgpack
from aiokafka import AIOKafkaConsumer

from shared.config.base_config import config

logger = logging.getLogger(__name__)


class KafkaConsumerWrapper:
    def __init__(self, topic: str, group_id: str) -> None:
        self._topic = topic
        self._group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._dlq = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=config.kafka.bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset=config.kafka.auto_offset_reset,
            value_deserializer=lambda v: msgpack.unpackb(v, raw=False),
            enable_auto_commit=False,
        )
        await self._consumer.start()
        self._running = True
        logger.info("Kafka consumer started (topic=%s, group=%s)", self._topic, self._group_id)

    def set_dlq(self, dlq) -> None:
        self._dlq = dlq

    async def consume(self, handler: Callable[[dict, dict], Awaitable[None]]) -> None:
        """Consume messages. handler receives (value, headers_dict)."""
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")

        batch_count = 0
        async for msg in self._consumer:
            if not self._running:
                break
            try:
                headers = {k: v for k, v in (msg.headers or [])}
                await handler(msg.value, headers)
                batch_count += 1
                if batch_count >= 200:
                    await self._consumer.commit()
                    batch_count = 0
            except Exception as e:
                logger.exception("Error processing message from %s (offset=%d)", self._topic, msg.offset)
                if self._dlq:
                    try:
                        await self._dlq.send(
                            self._topic, msg.value, str(e), type(e).__name__
                        )
                    except Exception:
                        logger.exception("Failed to send to DLQ for topic %s", self._topic)

        if batch_count > 0 and self._consumer:
            await self._consumer.commit()

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")

    @property
    def is_started(self) -> bool:
        return self._consumer is not None
