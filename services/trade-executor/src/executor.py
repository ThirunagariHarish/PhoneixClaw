import logging
import time
import uuid
from datetime import datetime, timezone

from services.trade_executor.src.buffer import calculate_buffered_price  # noqa: E402
from services.trade_executor.src.fill_tracker import FillTracker
from services.trade_executor.src.validator import trade_validator  # noqa: E402
from shared.broker.adapter import BrokerAdapter
from shared.broker.alpaca_adapter import AlpacaAuthError
from shared.broker.circuit_breaker import CircuitBreaker, CircuitOpenError
from shared.broker.factory import create_broker_adapter
from shared.kafka_utils.consumer import KafkaConsumerWrapper
from shared.kafka_utils.dlq import DeadLetterQueue
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import AccountSourceMapping, TradingAccount
from shared.retry import RetryExhaustedError, retry_async

logger = logging.getLogger(__name__)


class TradeExecutorService:
    def __init__(self, broker: BrokerAdapter | None = None) -> None:
        self.consumer = KafkaConsumerWrapper("approved-trades", "trade-executor-group")
        self.exit_consumer = KafkaConsumerWrapper("exit-signals", "trade-executor-exit-group")
        self.producer = KafkaProducerWrapper()
        self.broker = broker
        self._broker_cache: dict[str, BrokerAdapter] = {}
        self._verified_accounts: set[str] = set()
        self._failed_accounts: dict[str, str] = {}
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5, recovery_timeout=60.0,
            excluded_exceptions=(AlpacaAuthError,),
        )
        self._dry_run = False
        self._fill_tracker = FillTracker()

    async def start(self) -> None:
        from shared.config.base_config import config as app_config
        self._dry_run = app_config.risk.dry_run_mode
        await self.producer.start()
        dlq = DeadLetterQueue(self.producer)
        self.consumer.set_dlq(dlq)
        self.exit_consumer.set_dlq(dlq)
        await self.consumer.start()
        await self.exit_consumer.start()
        await self._fill_tracker.start()
        logger.info("Trade executor started (dry_run=%s)", self._dry_run)

    async def stop(self) -> None:
        await self._fill_tracker.stop()
        await self.consumer.stop()
        await self.exit_consumer.stop()
        await self.producer.stop()

    async def run(self) -> None:
        import asyncio
        await asyncio.gather(
            self.consumer.consume(self._handle_trade),
            self.exit_consumer.consume(self._handle_exit_signal),
            self._fill_tracker.run(),
        )

    async def _resolve_broker(self, trade: dict) -> BrokerAdapter | None:
        if self.broker:
            return self.broker

        ta_id = trade.get("trading_account_id")
        if not ta_id:
            channel_id = trade.get("channel_id")
            user_id = trade.get("user_id")
            if channel_id and user_id:
                try:
                    ch_uuid = uuid.UUID(channel_id)
                except (ValueError, TypeError):
                    ch_uuid = None
                if ch_uuid:
                    async with AsyncSessionLocal() as session:
                        from sqlalchemy import select
                        result = await session.execute(
                            select(AccountSourceMapping).where(
                                AccountSourceMapping.channel_id == ch_uuid,
                                AccountSourceMapping.enabled.is_(True),
                            )
                        )
                        mapping = result.scalar_one_or_none()
                        if mapping:
                            ta_id = str(mapping.trading_account_id)
                            trade["trading_account_id"] = ta_id

        if not ta_id:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                user_id = trade.get("user_id")
                if not user_id:
                    return None
                result = await session.execute(
                    select(TradingAccount).where(
                        TradingAccount.user_id == uuid.UUID(user_id),
                        TradingAccount.enabled.is_(True),
                    ).limit(1)
                )
                account = result.scalar_one_or_none()
                if account:
                    ta_id = str(account.id)
                    trade["trading_account_id"] = ta_id

        if not ta_id:
            return None

        if ta_id in self._broker_cache:
            return self._broker_cache[ta_id]

        async with AsyncSessionLocal() as session:
            account = await session.get(TradingAccount, uuid.UUID(ta_id))
            if not account:
                return None
            broker = create_broker_adapter(
                account.broker_type,
                account.credentials_encrypted,
                account.paper_mode,
            )
            if ta_id not in self._verified_accounts:
                await self._verify_broker(ta_id, broker, account)
            self._broker_cache[ta_id] = broker
            return broker

    async def _verify_broker(self, ta_id: str, broker: BrokerAdapter, account) -> None:
        """Run a one-time health check on first use of a broker to catch auth issues early."""
        base_url = getattr(broker, "base_url", "unknown")
        mode = "PAPER" if account.paper_mode else "LIVE"
        try:
            acct_info = await broker.get_account()
            self._verified_accounts.add(ta_id)
            self._failed_accounts.pop(ta_id, None)
            logger.info(
                "Broker verified for account %s (%s, mode=%s, url=%s, buying_power=$%.2f)",
                ta_id, account.display_name, mode, base_url,
                acct_info.get("buying_power", 0),
            )
        except AlpacaAuthError as e:
            error_msg = f"Broker auth FAILED ({mode} @ {base_url}): {e} — check API keys match the {mode.lower()} account"
            self._failed_accounts[ta_id] = error_msg
            logger.error("BROKER AUTH FAILED for account %s (%s): %s", ta_id, account.display_name, error_msg)
        except Exception as e:
            logger.warning("Broker health check inconclusive for %s: %s", ta_id, e)
            self._verified_accounts.add(ta_id)

    async def _handle_trade(self, trade: dict, headers: dict) -> None:
        trade_id = trade.get("trade_id", "unknown")
        start_time = time.monotonic()

        broker = await self._resolve_broker(trade)
        if not broker:
            await self._publish_result(
                trade, "REJECTED",
                error_message="No trading account found for this trade",
                start_time=start_time,
            )
            return

        ta_id = trade.get("trading_account_id", "")
        if ta_id in self._failed_accounts:
            await self._publish_result(
                trade, "REJECTED",
                error_message=self._failed_accounts[ta_id],
                start_time=start_time,
            )
            return

        is_valid, error = trade_validator.validate(trade)
        if not is_valid:
            await self._publish_result(trade, "REJECTED", error_message=error, start_time=start_time)
            return

        ticker = trade["ticker"]
        action = trade["action"]
        price = float(trade["price"])
        expiration = trade.get("expiration")
        option_type = trade["option_type"]
        strike = float(trade["strike"])

        buffered_price, buffer_pct = calculate_buffered_price(price, action, ticker)

        quantity_str = str(trade.get("quantity", "1"))
        is_percentage = "%" in quantity_str
        quantity = 1
        if not is_percentage:
            quantity = int(quantity_str)

        if not expiration:
            await self._publish_result(trade, "REJECTED", error_message="Missing expiration", start_time=start_time)
            return

        symbol = broker.format_option_symbol(ticker, expiration, option_type, strike)

        if self._dry_run:
            trade["broker_order_id"] = f"DRY-{trade_id[:8]}"
            trade["buffered_price"] = buffered_price
            trade["buffer_pct_used"] = buffer_pct
            trade["broker_symbol"] = symbol
            await self._publish_result(trade, "EXECUTED", start_time=start_time)
            logger.info("[DRY RUN] Trade %s: %s %d %s @ %.2f", trade_id, action, quantity, symbol, buffered_price)
            return

        try:
            order_id = await retry_async(
                self._circuit_breaker.call,
                broker.place_limit_order, symbol, quantity, action, buffered_price,
                max_retries=2, base_delay=1.0,
                retryable_exceptions=(ConnectionError, TimeoutError, OSError),
            )
            trade["broker_order_id"] = order_id
            trade["buffered_price"] = buffered_price
            trade["buffer_pct_used"] = buffer_pct
            trade["broker_symbol"] = symbol
            await self._publish_result(trade, "EXECUTED", start_time=start_time)
            await self._fill_tracker.track(order_id, trade, broker)
            logger.info("Executed trade %s: %s %d %s @ %.2f (buffered=%.2f, order=%s)",
                         trade_id, action, quantity, symbol, price, buffered_price, order_id)
        except AlpacaAuthError as e:
            logger.error("Auth failure for trade %s — rejecting immediately: %s", trade_id, e)
            self._failed_accounts[ta_id] = str(e)
            await self._publish_result(trade, "REJECTED", error_message=str(e), start_time=start_time)
        except CircuitOpenError:
            logger.error("Circuit breaker OPEN — trade %s deferred", trade_id)
            await self._publish_result(trade, "ERROR", error_message="BROKER_CIRCUIT_OPEN", start_time=start_time)
        except RetryExhaustedError as e:
            logger.error("Retries exhausted for trade %s: %s", trade_id, e)
            await self._publish_result(trade, "ERROR", error_message=f"BROKER_TIMEOUT: {e}", start_time=start_time)
        except Exception as e:
            logger.error("Failed to execute trade %s: %s", trade_id, e)
            await self._publish_result(trade, "ERROR", error_message=str(e), start_time=start_time)

    async def _handle_exit_signal(self, signal: dict, headers: dict) -> None:
        """Process an exit signal from the position monitor to close a position."""
        position_id = signal.get("position_id")
        action_type = signal.get("action", "MANUAL_EXIT")
        ticker = signal.get("ticker", "")
        quantity = signal.get("quantity", 1)
        current_price = signal.get("current_price", 0)
        user_id = signal.get("user_id", "")
        trading_account_id = signal.get("trading_account_id", "")

        logger.info("Exit signal: %s for position %s (%s)", action_type, position_id, ticker)

        trade = {
            "trade_id": str(uuid.uuid4()),
            "user_id": user_id,
            "trading_account_id": trading_account_id,
            "ticker": ticker,
            "action": "SELL",
            "strike": signal.get("strike", 0),
            "option_type": signal.get("option_type", "CALL"),
            "expiration": signal.get("expiration"),
            "quantity": quantity,
            "price": current_price,
            "source": "exit-signal",
            "raw_message": f"Auto-exit: {action_type}",
        }

        broker = await self._resolve_broker(trade)
        if not broker:
            logger.error("No broker for exit signal on position %s", position_id)
            return

        start_time = time.monotonic()
        symbol = signal.get("broker_symbol", "")
        if not symbol:
            exp = signal.get("expiration")
            if exp:
                symbol = broker.format_option_symbol(
                    ticker, exp, signal.get("option_type", "CALL"), signal.get("strike", 0)
                )

        try:
            if self._dry_run:
                order_id = f"DRY-EXIT-{trade['trade_id'][:8]}"
            else:
                sell_price = current_price * 0.97
                order_id = await broker.place_limit_order(symbol, quantity, "SELL", sell_price)

            trade["broker_order_id"] = order_id
            await self._publish_result(trade, "EXECUTED", start_time=start_time)

            from sqlalchemy import update as sa_update

            from shared.models.trade import Position
            async with AsyncSessionLocal() as session:
                await session.execute(
                    sa_update(Position)
                    .where(Position.id == int(position_id))
                    .values(
                        status="CLOSED",
                        close_reason=action_type,
                        close_price=current_price,
                        closed_at=datetime.now(timezone.utc),
                        realized_pnl=signal.get("pnl_amount"),
                    )
                )
                await session.commit()
            logger.info("Closed position %s via %s (order=%s)", position_id, action_type, order_id)
        except Exception as e:
            logger.error("Failed to close position %s: %s", position_id, e)
            await self._publish_result(trade, "ERROR", error_message=str(e), start_time=start_time)

    async def _update_trade_in_db(
        self, trade: dict, status: str, error_message: str | None = None, latency_ms: int = 0
    ) -> None:
        """Update the Trade row that was created by the gateway."""
        try:
            trade_id_str = trade.get("trade_id")
            if not trade_id_str:
                return

            from sqlalchemy import update

            from shared.models.trade import Trade

            async with AsyncSessionLocal() as session:
                stmt = (
                    update(Trade)
                    .where(Trade.trade_id == uuid.UUID(trade_id_str))
                    .values(
                        status=status,
                        processed_at=datetime.now(timezone.utc),
                        execution_latency_ms=latency_ms,
                        error_message=error_message,
                        rejection_reason=error_message if status == "REJECTED" else None,
                        broker_order_id=trade.get("broker_order_id"),
                        buffered_price=trade.get("buffered_price"),
                        buffer_pct_used=trade.get("buffer_pct_used"),
                        trading_account_id=(
                            uuid.UUID(trade["trading_account_id"])
                            if trade.get("trading_account_id")
                            else None
                        ),
                    )
                )
                result = await session.execute(stmt)
                await session.commit()

                if result.rowcount == 0:
                    logger.warning("Trade %s not found in DB for update, creating", trade_id_str)
                    await self._create_trade_fallback(trade, status, error_message, latency_ms, session)

        except Exception:
            logger.exception("Failed to update trade %s in DB", trade.get("trade_id"))

    async def _create_trade_fallback(
        self, trade: dict, status: str, error_message: str | None,
        latency_ms: int, session,
    ) -> None:
        """Insert trade if gateway didn't persist it."""
        from shared.models.trade import Trade

        user_id = trade.get("user_id")
        if not user_id:
            return

        expiration = None
        if trade.get("expiration"):
            try:
                expiration = datetime.strptime(trade["expiration"], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        record = Trade(
            trade_id=uuid.UUID(trade["trade_id"]),
            user_id=uuid.UUID(user_id),
            trading_account_id=(
                uuid.UUID(trade["trading_account_id"])
                if trade.get("trading_account_id")
                else None
            ),
            ticker=trade.get("ticker", ""),
            strike=trade.get("strike", 0),
            option_type=trade.get("option_type", "CALL"),
            expiration=expiration,
            action=trade.get("action", "BUY"),
            quantity=str(trade.get("quantity", "1")),
            price=trade.get("price", 0),
            source=trade.get("source", "chat"),
            raw_message=trade.get("raw_message"),
            status=status,
            error_message=error_message,
            rejection_reason=error_message if status == "REJECTED" else None,
            execution_latency_ms=latency_ms,
            broker_order_id=trade.get("broker_order_id"),
            buffered_price=trade.get("buffered_price"),
            buffer_pct_used=trade.get("buffer_pct_used"),
            processed_at=datetime.now(timezone.utc),
        )
        session.add(record)
        await session.commit()
        logger.info("Created fallback trade record %s", trade.get("trade_id"))

    async def _publish_result(
        self, trade: dict, status: str, error_message: str | None = None, start_time: float = 0
    ) -> None:
        latency_ms = int((time.monotonic() - start_time) * 1000) if start_time else 0
        trade["status"] = status
        trade["processed_at"] = datetime.now(timezone.utc).isoformat()
        trade["execution_latency_ms"] = latency_ms
        if error_message:
            trade["error_message"] = error_message

        await self._update_trade_in_db(trade, status, error_message, latency_ms)

        msg_headers = []
        user_id = trade.get("user_id", "")
        if user_id:
            msg_headers.append(("user_id", user_id.encode("utf-8")))

        await self.producer.send(
            "execution-results",
            value=trade,
            key=trade.get("trade_id", ""),
            headers=msg_headers or None,
        )

        audit_event = {
            "user_id": trade.get("user_id"),
            "trade_id": trade.get("trade_id"),
            "event_type": status,
            "event_data": {
                "ticker": trade.get("ticker"),
                "action": trade.get("action"),
                "price": trade.get("price"),
                "error": error_message,
            },
            "source_service": "trade-executor",
        }
        await self.producer.send(
            "trade-events-raw",
            value=audit_event,
            key=trade.get("trade_id", ""),
            headers=msg_headers or None,
        )
