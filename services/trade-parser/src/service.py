import logging
import os
import uuid

import httpx

from services.trade_parser.src.parser import parse_trade_message  # noqa: E402
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper

logger = logging.getLogger(__name__)

NLP_PARSER_URL = os.getenv("NLP_PARSER_URL", "http://nlp-parser:8020")


class TradeParserService:
    def __init__(self) -> None:
        self.consumer = KafkaConsumerWrapper("raw-messages", "trade-parser-group")
        self.producer = KafkaProducerWrapper()
        self._nlp_available = False

    async def start(self) -> None:
        await self.producer.start()
        await self.consumer.start()
        await self._check_nlp()
        logger.info("Trade parser service started (nlp=%s)", self._nlp_available)

    async def _check_nlp(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{NLP_PARSER_URL}/health")
                self._nlp_available = resp.status_code == 200
        except Exception:
            self._nlp_available = False
            logger.info("NLP parser not available, using regex only")

    async def stop(self) -> None:
        await self.consumer.stop()
        await self.producer.stop()
        logger.info("Trade parser service stopped")

    async def run(self) -> None:
        await self.consumer.consume(self._handle_message)

    async def _call_nlp(self, text: str, user_id: str, channel_id: str) -> dict | None:
        """Call the NLP parser service as fallback when regex fails."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{NLP_PARSER_URL}/parse",
                    json={"text": text, "user_id": user_id, "channel_id": channel_id},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("is_trade_signal") and data.get("ticker") and data.get("price"):
                        return data
        except Exception:
            logger.debug("NLP parser call failed for: %s", text[:80])
        return None

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
        actions = result["actions"]

        # Fallback to NLP parser when regex finds nothing
        if not actions and self._nlp_available:
            nlp_result = await self._call_nlp(raw_text, user_id, channel_id)
            if nlp_result:
                actions = [{
                    "action": nlp_result["action"],
                    "ticker": nlp_result["ticker"],
                    "strike": nlp_result.get("strike", 0),
                    "option_type": nlp_result.get("option_type", "CALL"),
                    "expiration": nlp_result.get("expiration"),
                    "price": nlp_result["price"],
                    "quantity": nlp_result.get("quantity", 1),
                    "is_percentage": False,
                }]
                logger.info("NLP parsed trade from: %s (confidence=%.2f, method=%s)",
                            raw_text[:80], nlp_result.get("confidence", 0),
                            nlp_result.get("method", "unknown"))

        if not actions:
            logger.info("No trade actions found in message (len=%d): %s", len(raw_text), raw_text[:200])
            return

        for action in actions:
            if not action.get("option_type"):
                action["option_type"] = "CALL"
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
            opt_char = (action["option_type"] or "?")[0]
            logger.info("Parsed trade: %s %s %s %s @ %.2f (trade_id=%s)",
                         action["action"], action["ticker"], action["strike"],
                         opt_char, action["price"], trade_id)
