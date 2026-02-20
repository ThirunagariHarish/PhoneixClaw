import logging
import time

from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import TradeEvent

logger = logging.getLogger(__name__)


class AuditWriterService:
    def __init__(self):
        self.consumer = KafkaConsumerWrapper("trade-events-raw", "audit-writer-group")
        self._buffer = []
        self._last_flush = time.monotonic()
        self.flush_interval = 0.5
        self.batch_size = 100

    async def start(self):
        await self.consumer.start()
        logger.info("Audit writer service started")

    async def stop(self):
        await self._flush()
        await self.consumer.stop()

    async def run(self):
        await self.consumer.consume(self._handle_event)

    async def _handle_event(self, event: dict, headers: dict):
        self._buffer.append(event)
        now = time.monotonic()
        if len(self._buffer) >= self.batch_size or (now - self._last_flush) >= self.flush_interval:
            await self._flush()

    async def _flush(self):
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        self._last_flush = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                for evt in batch:
                    te = TradeEvent(
                        user_id=evt.get("user_id"),
                        trade_id=evt.get("trade_id"),
                        event_type=evt.get("event_type", "UNKNOWN"),
                        event_data=evt.get("event_data", {}),
                        source_service=evt.get("source_service", "unknown"),
                    )
                    session.add(te)
                await session.commit()
            logger.debug("Flushed %d audit events", len(batch))
        except Exception:
            logger.exception("Failed to flush %d audit events", len(batch))
