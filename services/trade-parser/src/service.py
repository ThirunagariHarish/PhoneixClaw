import logging
import uuid

from services.trade_parser.src.parser import parse_trade_message  # noqa: E402
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper

logger = logging.getLogger(__name__)


class TradeParserService:
    def __init__(self) -> None:
        self.consumer = KafkaConsumerWrapper("raw-messages", "trade-parser-group")
        self.producer = KafkaProducerWrapper()

    async def start(self) -> None:
        await self.producer.start()
        await self.consumer.start()
        logger.info("Trade parser service started")

    async def stop(self) -> None:
        await self.consumer.stop()
        await self.producer.stop()
        logger.info("Trade parser service stopped")

    async def run(self) -> None:
        await self.consumer.consume(self._handle_message)

    async def _handle_message(self, message: dict, headers: dict) -> None:
        raw_text = message.get("content", "")
        raw_uid = headers.get("user_id") or headers.get(b"user_id")
        user_id = (
            raw_uid.decode("utf-8") if isinstance(raw_uid, bytes) else raw_uid
        ) if raw_uid else message.get("user_id", "")
        raw_cid = headers.get("channel_id") or headers.get(b"channel_id")
        channel_id = (
            raw_cid.decode("utf-8") if isinstance(raw_cid, bytes) else raw_cid
        ) if raw_cid else message.get("channel_id", "")
        source = message.get("source", "discord")
        source_message_id = message.get("message_id", "")
        source_author = message.get("author", "")

        result = parse_trade_message(raw_text)

        if not result["actions"]:
            logger.debug("No trade actions found in message: %s", raw_text[:100])
            return

        for action in result["actions"]:
            trade_id = str(uuid.uuid4())
            parsed_trade = {
                "trade_id": trade_id,
                "user_id": user_id,
                "channel_id": channel_id,
                **action,
                "source": source,
                "source_message_id": source_message_id,
                "source_author": source_author,
                "raw_message": raw_text,
            }
            msg_headers = []
            if user_id:
                msg_headers.append(("user_id", user_id.encode("utf-8")))
            if channel_id:
                msg_headers.append(("channel_id", channel_id.encode("utf-8")))

            await self.producer.send(
                "parsed-trades",
                value=parsed_trade,
                key=trade_id,
                headers=msg_headers or None,
            )
            logger.info("Parsed trade: %s %s %s %sC @ %.2f (trade_id=%s)",
                         action["action"], action["ticker"], action["strike"],
                         action["option_type"][0], action["price"], trade_id)
