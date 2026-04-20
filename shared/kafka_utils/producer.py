from __future__ import annotations
import logging

import msgpack
from aiokafka import AIOKafkaProducer

from shared.config.base_config import config

logger = logging.getLogger(__name__)


class KafkaProducerWrapper:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=config.kafka.bootstrap_servers,
            value_serializer=lambda v: msgpack.packb(v, use_bin_type=True),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            enable_idempotence=True,
            linger_ms=5,
            max_batch_size=32768,
        )
        await self._producer.start()
        logger.info("Kafka producer started (servers=%s)", config.kafka.bootstrap_servers)

    async def send(
        self,
        topic: str,
        value: dict,
        key: str | None = None,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started. Call start() first.")
        await self._producer.send(topic, value=value, key=key, headers=headers)
        logger.debug("Produced to %s (key=%s)", topic, key)

    async def send_and_wait(
        self,
        topic: str,
        value: dict,
        key: str | None = None,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started. Call start() first.")
        await self._producer.send_and_wait(topic, value=value, key=key, headers=headers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    @property
    def is_started(self) -> bool:
        return self._producer is not None
