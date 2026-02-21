import logging
import uuid
from datetime import datetime, timezone

from shared.config.base_config import config
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Trade

logger = logging.getLogger(__name__)


class TradeGatewayService:
    def __init__(self) -> None:
        self.consumer = KafkaConsumerWrapper("parsed-trades", "trade-gateway-group")
        self.producer = KafkaProducerWrapper()
        self.mode = config.gateway.approval_mode

    async def start(self) -> None:
        await self.producer.start()
        await self.consumer.start()
        logger.info("Trade gateway started (mode=%s)", self.mode)

    async def stop(self) -> None:
        await self.consumer.stop()
        await self.producer.stop()

    async def run(self) -> None:
        await self.consumer.consume(self._handle_trade)

    async def _persist_trade(self, trade: dict, status: str) -> None:
        """Insert a Trade row so the dashboard can show it immediately."""
        try:
            user_id = trade.get("user_id")
            if not user_id:
                return
            ta_id = trade.get("trading_account_id")
            expiration = None
            if trade.get("expiration"):
                try:
                    expiration = datetime.strptime(trade["expiration"], "%Y-%m-%d")
                except (ValueError, TypeError):
                    pass

            record = Trade(
                trade_id=uuid.UUID(trade["trade_id"]),
                user_id=uuid.UUID(user_id),
                trading_account_id=uuid.UUID(ta_id) if ta_id else None,
                ticker=trade.get("ticker", ""),
                strike=trade.get("strike", 0),
                option_type=trade.get("option_type", "CALL"),
                expiration=expiration,
                action=trade.get("action", "BUY"),
                quantity=str(trade.get("quantity", "1")),
                price=trade.get("price", 0),
                source=trade.get("source", "chat"),
                source_message_id=trade.get("source_message_id"),
                source_author=trade.get("source_author"),
                raw_message=trade.get("raw_message"),
                status=status,
                approved_by=trade.get("approved_by"),
                approved_at=datetime.now(timezone.utc) if status == "APPROVED" else None,
            )
            async with AsyncSessionLocal() as session:
                session.add(record)
                await session.commit()
            logger.info("Persisted trade %s (status=%s)", trade.get("trade_id"), status)
        except Exception:
            logger.exception("Failed to persist trade %s to DB", trade.get("trade_id"))

    async def _handle_trade(self, trade: dict, headers: dict) -> None:
        trade_id = trade.get("trade_id", "unknown")

        if self.mode == "auto":
            trade["status"] = "APPROVED"
            trade["approved_by"] = "auto-gateway"
            trade["approved_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Auto-approved trade %s: %s %s", trade_id, trade.get("action"), trade.get("ticker"))
        else:
            trade["status"] = "PENDING"
            await self._persist_trade(trade, "PENDING")
            logger.info("Trade %s pending manual approval", trade_id)
            return

        await self._persist_trade(trade, "APPROVED")

        msg_headers = []
        user_id = trade.get("user_id", "")
        if user_id:
            msg_headers.append(("user_id", user_id.encode("utf-8")))
        ta_id = trade.get("trading_account_id", "")
        if ta_id:
            msg_headers.append(("trading_account_id", ta_id.encode("utf-8")))

        await self.producer.send(
            "approved-trades",
            value=trade,
            key=trade_id,
            headers=msg_headers or None,
        )
