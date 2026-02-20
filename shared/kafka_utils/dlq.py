import logging
from datetime import datetime, timezone

from shared.kafka_utils.producer import KafkaProducerWrapper

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    def __init__(self, producer: KafkaProducerWrapper):
        self._producer = producer

    async def send(self, original_topic: str, message: dict, error: str, error_type: str = "UNKNOWN"):
        dlq_topic = f"dlq-{original_topic}"
        envelope = {
            "original_topic": original_topic,
            "original_message": message,
            "error": error,
            "error_type": error_type,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._producer.send(dlq_topic, value=envelope)
            logger.warning("Message sent to DLQ %s: %s", dlq_topic, error)
        except Exception:
            logger.exception("Failed to send to DLQ %s", dlq_topic)
