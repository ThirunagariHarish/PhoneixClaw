import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.config.base_config import config
from shared.feature_flags import feature_flags
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import AccountSourceMapping, Channel, Trade, TradingAccount

logger = logging.getLogger(__name__)

DEDUP_WINDOW_MINUTES = 5


def _is_uuid(val: str) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


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

    async def _is_duplicate(self, trade: dict) -> bool:
        """Check if a very similar trade was already created within the dedup window."""
        user_id = trade.get("user_id")
        if not user_id:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Trade.trade_id).where(
                        Trade.user_id == uuid.UUID(user_id),
                        Trade.ticker == (trade.get("ticker") or ""),
                        Trade.strike == (trade.get("strike") or 0),
                        Trade.option_type == (trade.get("option_type") or "CALL"),
                        Trade.action == (trade.get("action") or "BUY"),
                        Trade.price == (trade.get("price") or 0),
                        Trade.created_at >= cutoff,
                    ).limit(1)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    logger.info(
                        "Duplicate trade skipped %s: %s %s %s @ %s (matches existing %s)",
                        trade.get("trade_id"), trade.get("action"),
                        trade.get("ticker"), trade.get("strike"),
                        trade.get("price"), existing,
                    )
                    return True
        except Exception:
            logger.exception("Dedup check failed for trade %s", trade.get("trade_id"))
        return False

    async def _persist_trade(self, trade: dict, status: str) -> None:
        """Insert a Trade row so the dashboard can show it immediately."""
        try:
            user_id = trade.get("user_id")
            if not user_id:
                return
            ta_id = trade.get("trading_account_id")
            ch_id = trade.get("channel_id")
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
                channel_id=uuid.UUID(ch_id) if ch_id and _is_uuid(ch_id) else None,
                ticker=trade.get("ticker", ""),
                strike=trade.get("strike") or 0,
                option_type=trade.get("option_type") or "CALL",
                expiration=expiration,
                action=trade.get("action", "BUY"),
                quantity=str(trade.get("quantity") or "1"),
                price=trade.get("price") or 0,
                source=trade.get("source", "chat"),
                source_message_id=trade.get("source_message_id"),
                source_author=trade.get("source_author"),
                raw_message=trade.get("raw_message"),
                status=status,
                approved_by=trade.get("approved_by"),
                approved_at=datetime.now(timezone.utc) if status == "IN_PROGRESS" else None,
            )
            async with AsyncSessionLocal() as session:
                session.add(record)
                await session.commit()
            logger.info("Persisted trade %s (status=%s, channel=%s)", trade.get("trade_id"), status, ch_id)
        except Exception:
            logger.exception("Failed to persist trade %s to DB", trade.get("trade_id"))

    async def _resolve_trading_account(self, trade: dict) -> str | None:
        """Resolve trading_account_id from trade. Also resolves channel_id to a UUID."""
        ta_id = trade.get("trading_account_id")

        user_id = trade.get("user_id")
        if not user_id:
            return str(ta_id) if ta_id else None

        channel_id_raw = trade.get("channel_id")
        ch_uuid: uuid.UUID | None = None
        if channel_id_raw:
            try:
                ch_uuid = uuid.UUID(channel_id_raw)
            except (ValueError, TypeError):
                pass
            if ch_uuid is None:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Channel).where(
                            Channel.channel_identifier == str(channel_id_raw)
                        ).limit(1)
                    )
                    ch = result.scalar_one_or_none()
                    if ch:
                        ch_uuid = ch.id

        if ch_uuid:
            trade["channel_id"] = str(ch_uuid)

        if ta_id:
            return str(ta_id) if not isinstance(ta_id, str) else ta_id

        if ch_uuid:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AccountSourceMapping).where(
                        AccountSourceMapping.channel_id == ch_uuid,
                        AccountSourceMapping.enabled.is_(True),
                    ).limit(1)
                )
                mapping = result.scalars().first()
                if mapping:
                    return str(mapping.trading_account_id)

        try:
            user_uuid = uuid.UUID(user_id)
        except (ValueError, TypeError, AttributeError):
            return None

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TradingAccount).where(
                    TradingAccount.user_id == user_uuid,
                    TradingAccount.enabled.is_(True),
                ).limit(1)
            )
            account = result.scalar_one_or_none()
            if account:
                return str(account.id)
        return None

    async def _handle_trade(self, trade: dict, headers: dict) -> None:
        trade_id = trade.get("trade_id", "unknown")
        user_id = trade.get("user_id")

        if not feature_flags.is_enabled("audit_logging", user_id):
            logger.debug("Audit logging disabled for user %s", user_id)

        override_manual = feature_flags.is_enabled("manual_approval", user_id)
        effective_mode = "manual" if override_manual else self.mode

        if feature_flags.is_enabled("paper_trading_only", user_id):
            trade["paper_mode"] = True

        ta_id = await self._resolve_trading_account(trade)
        if ta_id:
            trade["trading_account_id"] = ta_id

        if await self._is_duplicate(trade):
            return

        if effective_mode == "auto":
            trade["status"] = "IN_PROGRESS"
            trade["approved_by"] = "auto-gateway"
            trade["approved_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Auto-approved trade %s: %s %s", trade_id, trade.get("action"), trade.get("ticker"))
        else:
            trade["status"] = "PENDING"
            await self._persist_trade(trade, "PENDING")
            logger.info("Trade %s pending manual approval (flags: manual_approval=%s)", trade_id, override_manual)
            return

        await self._persist_trade(trade, "IN_PROGRESS")

        msg_headers = []
        user_id = trade.get("user_id", "")
        if user_id:
            msg_headers.append(("user_id", user_id.encode("utf-8")))
        if ta_id:
            msg_headers.append(("trading_account_id", ta_id.encode("utf-8")))

        await self.producer.send(
            "approved-trades",
            value=trade,
            key=trade_id,
            headers=msg_headers or None,
        )
