import asyncio
import logging
import time
import uuid

from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import RawMessage

logger = logging.getLogger(__name__)

MAX_FLUSH_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0


class RawMessageWriterService:
    def __init__(self):
        self.consumer = KafkaConsumerWrapper("raw-messages", "raw-message-writer-group")
        self._buffer: list[dict] = []
        self._last_flush = time.monotonic()
        self.flush_interval = 0.5
        self.batch_size = 100
        self._total_written = 0
        self._total_errors = 0

    async def start(self):
        await self.consumer.start()
        logger.info("Raw message writer service started")

    async def stop(self):
        await self._flush()
        await self.consumer.stop()
        logger.info(
            "Raw message writer stopped (total_written=%d, total_errors=%d)",
            self._total_written, self._total_errors,
        )

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

        for attempt in range(1, MAX_FLUSH_RETRIES + 1):
            try:
                async with AsyncSessionLocal() as session:
                    written = 0
                    for msg in batch:
                        user_id = msg.get("user_id")
                        if not user_id:
                            logger.warning("Skipping message without user_id: %s", msg.get("message_id"))
                            continue
                        try:
                            parsed_user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
                        except (ValueError, AttributeError):
                            logger.warning("Skipping message with invalid user_id: %s", user_id)
                            continue
                        try:
                            ds_id_raw = msg.get("data_source_id")
                            parsed_ds_id = (
                                uuid.UUID(ds_id_raw)
                                if ds_id_raw and isinstance(ds_id_raw, str)
                                else ds_id_raw
                            )
                        except (ValueError, AttributeError):
                            logger.warning("Invalid data_source_id %s, setting to None", ds_id_raw)
                            parsed_ds_id = None
                        rm = RawMessage(
                            user_id=parsed_user_id,
                            data_source_id=parsed_ds_id,
                            source_type=msg.get("source_type", "discord"),
                            channel_name=msg.get("channel_name"),
                            author=msg.get("author"),
                            content=msg.get("content", ""),
                            source_message_id=msg.get("source_message_id"),
                            raw_metadata=msg.get("raw_metadata", {}),
                        )
                        session.add(rm)
                        written += 1
                    await session.commit()
                self._total_written += written
                logger.info("Flushed %d raw messages (total=%d)", written, self._total_written)
                return
            except Exception:
                self._total_errors += len(batch)
                if attempt < MAX_FLUSH_RETRIES:
                    logger.warning(
                        "Flush attempt %d/%d failed for %d messages, retrying in %.1fs",
                        attempt, MAX_FLUSH_RETRIES, len(batch), RETRY_DELAY_SECONDS,
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                else:
                    logger.exception(
                        "Failed to flush %d raw messages after %d attempts (dropped)",
                        len(batch), MAX_FLUSH_RETRIES,
                    )
