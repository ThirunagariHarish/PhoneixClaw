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
from shared.models.trade import AccountSourceMapping, Channel, Position, TradePipeline, TradingAccount
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
        channel_id_raw = trade.get("channel_id")
        ch_uuid: uuid.UUID | None = None
        if channel_id_raw:
            try:
                ch_uuid = uuid.UUID(channel_id_raw)
            except (ValueError, TypeError):
                ch_uuid = None

        if not ta_id and ch_uuid is None and channel_id_raw and trade.get("user_id"):
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Channel).where(Channel.channel_identifier == channel_id_raw).limit(1)
                )
                ch = result.scalar_one_or_none()
                if ch:
                    ch_uuid = ch.id
                    trade["_channel_uuid"] = str(ch.id)

        if not ta_id and ch_uuid and trade.get("user_id"):
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(AccountSourceMapping).where(
                        AccountSourceMapping.channel_id == ch_uuid,
                        AccountSourceMapping.enabled.is_(True),
                    ).limit(1)
                )
                mapping = result.scalars().first()
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

        async with AsyncSessionLocal() as session:
            account = await session.get(TradingAccount, uuid.UUID(ta_id))
            if not account:
                return None

            paper_mode = account.paper_mode
            pipeline_ch_uuid = ch_uuid

            if pipeline_ch_uuid is None and channel_id_raw:
                try:
                    pipeline_ch_uuid = uuid.UUID(channel_id_raw)
                except (ValueError, TypeError):
                    pass
                if pipeline_ch_uuid is None:
                    result = await session.execute(
                        select(Channel).where(Channel.channel_identifier == channel_id_raw).limit(1)
                    )
                    ch = result.scalar_one_or_none()
                    if ch:
                        pipeline_ch_uuid = ch.id

            if pipeline_ch_uuid:
                from sqlalchemy import select
                result = await session.execute(
                    select(TradePipeline).where(
                        TradePipeline.trading_account_id == uuid.UUID(ta_id),
                        TradePipeline.channel_id == pipeline_ch_uuid,
                    )
                )
                pipeline = result.scalar_one_or_none()
                if pipeline is not None:
                    paper_mode = pipeline.paper_mode
                    logger.info(
                        "Pipeline %s paper_mode=%s for account %s",
                        pipeline.id, paper_mode, ta_id,
                    )

            cache_key = f"{ta_id}:{'paper' if paper_mode else 'live'}"

            if cache_key in self._failed_accounts:
                trade["_broker_failed"] = self._failed_accounts[cache_key]
                trade["_broker_cache_key"] = cache_key
                return self._broker_cache.get(cache_key)

            if cache_key in self._broker_cache:
                trade["_broker_cache_key"] = cache_key
                return self._broker_cache[cache_key]

            broker = create_broker_adapter(
                account.broker_type,
                account.credentials_encrypted,
                paper_mode,
            )
            if cache_key not in self._verified_accounts:
                await self._verify_broker(cache_key, broker, account, paper_mode)
            if cache_key in self._failed_accounts:
                trade["_broker_failed"] = self._failed_accounts[cache_key]
            trade["_broker_cache_key"] = cache_key
            self._broker_cache[cache_key] = broker
            return broker

    async def _verify_broker(
        self, cache_key: str, broker: BrokerAdapter, account, paper_mode: bool | None = None,
    ) -> None:
        """Run a one-time health check on first use of a broker to catch auth issues early."""
        effective_paper = paper_mode if paper_mode is not None else account.paper_mode
        base_url = getattr(broker, "base_url", "unknown")
        mode = "PAPER" if effective_paper else "LIVE"
        try:
            acct_info = await broker.get_account()
            self._verified_accounts.add(cache_key)
            self._failed_accounts.pop(cache_key, None)
            logger.info(
                "Broker verified for account %s (%s, mode=%s, url=%s, buying_power=$%.2f)",
                cache_key, account.display_name, mode, base_url,
                acct_info.get("buying_power", 0),
            )
        except AlpacaAuthError as e:
            error_msg = (
                f"Broker auth FAILED ({mode} @ {base_url}): {e}"
                f" — check API keys match the {mode.lower()} account"
            )
            self._failed_accounts[cache_key] = error_msg
            logger.error("BROKER AUTH FAILED for account %s (%s): %s", cache_key, account.display_name, error_msg)
        except Exception as e:
            logger.warning("Broker health check inconclusive for %s: %s", cache_key, e)
            self._verified_accounts.add(cache_key)

    async def _create_dry_run_position(self, trade: dict, fill_price: float, quantity: int) -> None:
        """Create a simulated Position for dry-run BUY trades so they appear on the Positions page."""
        user_id = trade.get("user_id")
        ta_id = trade.get("trading_account_id")
        if not user_id or not ta_id:
            return
        exp = None
        if trade.get("expiration"):
            try:
                exp = datetime.strptime(trade["expiration"], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                existing = await session.execute(
                    select(Position).where(
                        Position.user_id == uuid.UUID(user_id),
                        Position.broker_symbol == (trade.get("broker_symbol") or ""),
                        Position.status == "OPEN",
                    )
                )
                pos = existing.scalar_one_or_none()
                if pos:
                    total_cost = float(pos.total_cost) + (fill_price * quantity * 100)
                    total_qty = pos.quantity + quantity
                    pos.avg_entry_price = total_cost / (total_qty * 100) if total_qty else fill_price
                    pos.quantity = total_qty
                    pos.total_cost = total_cost
                    await session.commit()
                else:
                    new_pos = Position(
                        user_id=uuid.UUID(user_id),
                        trading_account_id=uuid.UUID(ta_id),
                        ticker=trade.get("ticker", ""),
                        strike=trade.get("strike", 0),
                        option_type=trade.get("option_type", "CALL"),
                        expiration=exp or datetime.now(timezone.utc),
                        quantity=quantity,
                        avg_entry_price=fill_price,
                        total_cost=fill_price * quantity * 100,
                        profit_target=trade.get("profit_target", 0.30),
                        stop_loss=trade.get("stop_loss", 0.20),
                        high_water_mark=fill_price,
                        broker_symbol=trade.get("broker_symbol", ""),
                        status="OPEN",
                    )
                    session.add(new_pos)
                    await session.commit()
                logger.info("[DRY RUN] Position created/updated for %s", trade.get("ticker"))
        except Exception:
            logger.exception("Failed to create dry-run position for trade %s", trade.get("trade_id"))

    async def _handle_trade(self, trade: dict, headers: dict) -> None:
        trade_id = trade.get("trade_id", "unknown")
        start_time = time.monotonic()

        logger.info(
            ">>> Executor received trade %s: %s %s @ %s (user=%s, account=%s, dry_run=%s)",
            trade_id, trade.get("action"), trade.get("ticker"),
            trade.get("price"), trade.get("user_id"),
            trade.get("trading_account_id"), self._dry_run,
        )

        # Merge headers into trade for broker resolution (gateway sends user_id/ta_id in headers)
        if headers:
            raw_uid = headers.get("user_id") or headers.get(b"user_id")
            if raw_uid and not trade.get("user_id"):
                trade["user_id"] = raw_uid.decode("utf-8") if isinstance(raw_uid, bytes) else raw_uid
            raw_ta = headers.get("trading_account_id") or headers.get(b"trading_account_id")
            if raw_ta and not trade.get("trading_account_id"):
                trade["trading_account_id"] = (
                    raw_ta.decode("utf-8") if isinstance(raw_ta, bytes) else raw_ta
                )

        broker = await self._resolve_broker(trade)
        if not broker:
            logger.warning(
                "No trading account for trade %s: user_id=%s, channel_id=%s",
                trade_id, trade.get("user_id"), trade.get("channel_id"),
            )
            await self._publish_result(
                trade, "REJECTED",
                error_message="No trading account found for this trade",
                start_time=start_time,
            )
            return

        if trade.get("_broker_failed"):
            await self._publish_result(
                trade, "REJECTED",
                error_message=trade["_broker_failed"],
                start_time=start_time,
            )
            return

        is_valid, error = trade_validator.validate(trade)
        if not is_valid:
            logger.warning("Validation failed for trade %s: %s", trade_id, error)
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
            logger.warning("Trade %s rejected: missing expiration", trade_id)
            await self._publish_result(trade, "REJECTED", error_message="Missing expiration", start_time=start_time)
            return

        symbol = broker.format_option_symbol(ticker, expiration, option_type, strike)

        if self._dry_run:
            trade["broker_order_id"] = f"DRY-{trade_id[:8]}"
            trade["buffered_price"] = buffered_price
            trade["buffer_pct_used"] = buffer_pct
            trade["broker_symbol"] = symbol
            await self._publish_result(trade, "EXECUTED", start_time=start_time)
            if action.upper() == "BUY":
                await self._create_dry_run_position(trade, buffered_price, quantity)
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
            fail_key = trade.get("_broker_cache_key", trade.get("trading_account_id", ""))
            self._failed_accounts[fail_key] = str(e)
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
