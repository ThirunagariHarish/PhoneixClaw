import logging
import time
import uuid

from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import RawMessage

logger = logging.getLogger(__name__)


class RawMessageWriterService:
    def __init__(self):
        self.consumer = KafkaConsumerWrapper("raw-messages", "raw-message-writer-group")
        self._buffer: list[dict] = []
        self._last_flush = time.monotonic()
        self.flush_interval = 0.5
        self.batch_size = 100

    async def start(self):
        await self.consumer.start()
        logger.info("Raw message writer service started")

    async def stop(self):
        await self._flush()
        await self.consumer.stop()

    async def run(self):
        await self.consumer.consume(self._handle_message)

    async def _handle_message(self, msg: dict, headers: dict):
        self._buffer.append(msg)
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
                for msg in batch:
                    user_id = msg.get("user_id")
                    if not user_id:
                        continue
                    rm = RawMessage(
                        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                        data_source_id=(
                            uuid.UUID(msg["data_source_id"])
                            if msg.get("data_source_id") and isinstance(msg["data_source_id"], str)
                            else msg.get("data_source_id")
                        ),
                        source_type=msg.get("source_type", "discord"),
                        channel_name=msg.get("channel_name"),
                        author=msg.get("author"),
                        content=msg.get("content", ""),
                        source_message_id=msg.get("source_message_id"),
                        raw_metadata=msg.get("raw_metadata", {}),
                    )
                    session.add(rm)
                await session.commit()
            logger.debug("Flushed %d raw messages", len(batch))
        except Exception:
            logger.exception("Failed to flush %d raw messages", len(batch))
