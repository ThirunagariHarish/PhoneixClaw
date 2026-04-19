"""Single agent's Redis stream processing loop."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.sql import func

from services.pipeline_worker.src.config import settings
from services.pipeline_worker.src.pipeline import (
    decision_fuser,
    enricher,
    market_gate,
    publisher,
    risk_checker,
    signal_parser,
    ta_analyzer,
)
from services.pipeline_worker.src.pipeline.inference_client import InferenceClient
from shared.broker.adapter import BrokerAdapter
from shared.broker.factory import create_broker_adapter
from shared.db.models.agent import Agent, PipelineWorkerState
from shared.db.models.agent_trade import AgentTrade
from shared.db.models.trading_account import TradingAccount

logger = logging.getLogger(__name__)


@dataclass
class WorkerStats:
    signals_processed: int = 0
    trades_executed: int = 0
    signals_skipped: int = 0
    started_at: float = field(default_factory=time.monotonic)
    last_heartbeat: float = 0.0


class AgentWorker:
    """Processes messages from Redis stream(s) through the ML pipeline for a single agent."""

    def __init__(
        self,
        agent_id: str,
        connector_ids: list[str],
        config: dict,
        redis_client: aioredis.Redis,
        session_factory: Any,
        user_id: str,
    ) -> None:
        self.agent_id = agent_id
        self.connector_ids = connector_ids
        self.config = config
        self.redis = redis_client
        self._session_factory = session_factory
        self._user_id = user_id
        self._stats = WorkerStats()
        self._inference = InferenceClient(
            inference_url=config.get("inference_service_url", settings.INFERENCE_SERVICE_URL),
        )
        self._running = False
        self._broker_adapter: Optional[BrokerAdapter] = None

        self._group_name = f"pipeline-{agent_id}"
        self._consumer_name = "worker-1"
        self._stream_keys = [f"stream:channel:{cid}" for cid in connector_ids]
        self._kill_switch_group = "pipeline-kill-switch"
        self._kill_switch_stream = "stream:kill-switch"

    @property
    def stats(self) -> dict:
        uptime = time.monotonic() - self._stats.started_at
        return {
            "agent_id": self.agent_id,
            "signals_processed": self._stats.signals_processed,
            "trades_executed": self._stats.trades_executed,
            "signals_skipped": self._stats.signals_skipped,
            "uptime_seconds": round(uptime, 1),
            "circuit_state": self._inference.circuit_state,
        }

    async def _init_broker_adapter(self) -> None:
        """Initialize broker adapter based on agent config."""
        broker_type = self.config.get("broker_type")
        if not broker_type:
            logger.warning("Agent %s has no broker_type; trades will fail", self.agent_id)
            return

        broker_account_id = self.config.get("broker_account_id")

        async with self._session_factory() as session:
            # If broker_account_id is specified, use that account
            if broker_account_id:
                result = await session.execute(
                    select(TradingAccount).where(
                        TradingAccount.id == broker_account_id,
                        TradingAccount.user_id == self._user_id,
                    )
                )
                account = result.scalar_one_or_none()
                if not account:
                    logger.error(
                        "Agent %s: broker_account_id %s not found for user %s",
                        self.agent_id, broker_account_id, self._user_id
                    )
                    return
            else:
                # Fall back to user's default account for this broker_type
                result = await session.execute(
                    select(TradingAccount).where(
                        TradingAccount.user_id == self._user_id,
                        TradingAccount.broker == broker_type,
                        TradingAccount.is_active == True,  # noqa: E712
                    ).limit(1)
                )
                account = result.scalar_one_or_none()
                if not account:
                    logger.error(
                        "Agent %s: no active %s account for user %s",
                        self.agent_id, broker_type, self._user_id
                    )
                    return

            # Create adapter
            try:
                paper_mode = account.account_type == "paper"
                self._broker_adapter = create_broker_adapter(
                    broker_type,
                    account.credentials_encrypted.encode() if isinstance(account.credentials_encrypted, str)
                    else account.credentials_encrypted,
                    paper_mode=paper_mode,
                )
                logger.info(
                    "Agent %s: broker adapter initialized (%s, %s mode)",
                    self.agent_id, broker_type, account.account_type
                )
            except Exception as exc:
                logger.error(
                    "Agent %s: failed to init broker adapter: %s",
                    self.agent_id, exc, exc_info=True
                )

    async def run(self) -> None:
        """Main loop: create consumer groups, then xreadgroup in a loop."""
        self._running = True

        # Initialize broker adapter
        await self._init_broker_adapter()

        # Create consumer groups
        for key in self._stream_keys:
            try:
                await self.redis.xgroup_create(key, self._group_name, id="0", mkstream=True)
                logger.info("Created consumer group %s on %s", self._group_name, key)
            except Exception:
                pass  # group already exists

        # Create kill-switch consumer group
        try:
            await self.redis.xgroup_create(
                self._kill_switch_stream, self._kill_switch_group, id="0", mkstream=True
            )
        except Exception:
            pass

        async with httpx.AsyncClient() as http_client:
            while self._running:
                try:
                    # Check kill-switch
                    await self._check_kill_switch()
                    if not self._running:
                        break

                    await self._read_and_process(http_client)
                    await self._maybe_heartbeat()
                except asyncio.CancelledError:
                    logger.info("Worker %s cancelled — shutting down", self.agent_id)
                    break
                except Exception as exc:
                    logger.error("Worker %s error: %s", self.agent_id, exc, exc_info=True)
                    await asyncio.sleep(2)

        # Close broker adapter
        if self._broker_adapter and hasattr(self._broker_adapter, "close"):
            try:
                await self._broker_adapter.close()
            except Exception:
                pass

        self._running = False
        logger.info("Worker %s stopped", self.agent_id)

    async def _check_kill_switch(self) -> None:
        """Check kill-switch stream for shutdown signals."""
        try:
            messages = await self.redis.xreadgroup(
                self._kill_switch_group,
                self._consumer_name,
                {self._kill_switch_stream: ">"},
                count=1,
                block=100,
            )
            if messages:
                logger.warning("Worker %s received kill-switch signal — stopping", self.agent_id)
                self._running = False
        except Exception as exc:
            logger.debug("Kill-switch check error (non-fatal): %s", exc)

    async def _read_and_process(self, http_client: httpx.AsyncClient) -> None:
        """XREADGROUP from all streams, process each message."""
        streams = {key: ">" for key in self._stream_keys}
        messages = await self.redis.xreadgroup(
            self._group_name,
            self._consumer_name,
            streams,
            count=10,
            block=5000,
        )
        if not messages:
            return

        for stream_key, entries in messages:
            for msg_id, data in entries:
                try:
                    content = data.get("content", "")
                    author = data.get("author", "")
                    channel = data.get("channel", "")
                    await self._process_signal(content, author, channel, http_client)
                except Exception as exc:
                    logger.error(
                        "Worker %s failed on message %s: %s",
                        self.agent_id, msg_id, exc, exc_info=True,
                    )
                finally:
                    stream_name = stream_key if isinstance(stream_key, str) else stream_key.decode()
                    await self.redis.xack(stream_name, self._group_name, msg_id)
                    self._stats.signals_processed += 1

    async def _process_signal(
        self,
        content: str,
        author: str,
        channel: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Run the full pipeline: parse → market gate → enrich → infer → risk → TA → fuse → publish."""

        # Step 1: Parse
        parsed = signal_parser.parse_signal(content, author=author, channel=channel)
        if parsed is None:
            self._stats.signals_skipped += 1
            return

        ticker = parsed.ticker
        logger.info("Worker %s processing signal: %s %s", self.agent_id, parsed.direction, ticker)

        # Step 2: Market hours
        market = market_gate.check_market_hours()
        market_dict = {
            "is_open": market.is_open,
            "session_type": market.session_type,
            "opens_at": market.opens_at,
            "closes_at": market.closes_at,
        }

        # Step 3: Enrich (non-blocking, degrade gracefully)
        features = await enricher.enrich_signal(
            ticker, http_client, settings.FEATURE_PIPELINE_URL,
        )

        signal_dict = {
            "ticker": ticker,
            "direction": parsed.direction,
            "strike": parsed.strike,
            "expiry": parsed.expiry,
            "entry_price": parsed.entry_price,
            "option_type": parsed.option_type,
            "confidence": parsed.confidence,
            "raw_content": parsed.raw_content,
            "author": parsed.author,
        }
        signal_features = {**signal_dict, **features}

        # Step 4: Inference
        prediction_result = await self._inference.predict(
            ticker, self.agent_id, signal_features, http_client,
        )
        prediction_dict = {
            "prediction": prediction_result.prediction,
            "confidence": prediction_result.confidence,
            "model_used": prediction_result.model_used,
            "reasoning": prediction_result.reasoning,
        }

        # Step 5: Risk check
        async with self._session_factory() as session:
            risk_result = await risk_checker.check_risk(
                signal_dict, prediction_dict, self.agent_id, self.config, session,
            )
        risk_dict = {
            "approved": risk_result.approved,
            "reason": risk_result.reason,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in risk_result.checks],
        }

        # Step 6: TA
        ta_result = await ta_analyzer.analyze(ticker)
        ta_dict = {
            "rsi": ta_result.rsi,
            "macd_signal": ta_result.macd_signal,
            "bb_position": ta_result.bb_position,
            "adx": ta_result.adx,
            "overall_bias": ta_result.overall_bias,
            "confidence_adjustment": ta_result.confidence_adjustment,
        }

        # Step 7: Fuse
        decision = decision_fuser.fuse(
            signal_dict, prediction_dict, risk_dict, ta_dict, market_dict, self.config,
        )

        # Step 8: Publish
        decision_out = {
            "action": decision.action,
            "final_confidence": decision.final_confidence,
            "reasons": decision.reasons,
            "ticker": ticker,
            "direction": parsed.direction,
            "execution_params": decision.execution_params,
        }

        if decision.action == "EXECUTE" and decision.execution_params:
            await self._execute_trade(parsed, signal_dict, decision, http_client)
        elif decision.action == "WATCHLIST":
            await publisher.publish_watchlist(
                http_client, settings.BROKER_GATEWAY_URL, ticker, self.agent_id,
            )
        else:
            self._stats.signals_skipped += 1

        await publisher.publish_decision(self.redis, self.agent_id, decision_out)
        await publisher.log_to_api(http_client, settings.API_BASE_URL, self.agent_id, {
            "level": "INFO",
            "message": f"Pipeline decision: {decision.action} for {ticker}",
            "context": decision_out,
        })

    async def _execute_trade(
        self,
        parsed,
        signal_dict: dict,
        decision,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Execute trade via broker adapter with position tracking."""
        dry_run = self.config.get("dry_run_mode", False)
        ticker = parsed.ticker
        direction = parsed.direction
        side = decision.execution_params.get("side", "buy").lower()
        qty = decision.execution_params.get("qty", 1)

        # Handle percentage-sell quantity calculation
        if parsed.is_percentage and direction == "SELL":
            async with self._session_factory() as session:
                qty = await self._calculate_percentage_sell_qty(
                    session, ticker, parsed, qty
                )
                if qty <= 0:
                    logger.warning(
                        "Agent %s: percentage-sell resulted in qty=0 for %s",
                        self.agent_id, ticker
                    )
                    self._stats.signals_skipped += 1
                    return

        # Dry-run mode: log intent but don't execute
        if dry_run:
            logger.info(
                "Agent %s DRY-RUN: would %s %d %s at $%.2f",
                self.agent_id, side.upper(), qty, ticker,
                parsed.entry_price or 0.0
            )
            await publisher.log_to_api(http_client, settings.API_BASE_URL, self.agent_id, {
                "level": "INFO",
                "message": f"DRY-RUN: {side.upper()} {qty} {ticker}",
                "context": {"signal": signal_dict, "decision": decision.execution_params},
            })
            self._stats.signals_skipped += 1
            return

        # Execute via broker adapter
        if not self._broker_adapter:
            logger.error("Agent %s: no broker adapter initialized", self.agent_id)
            self._stats.signals_skipped += 1
            return

        try:
            symbol = decision.execution_params.get("symbol", ticker)
            price = parsed.entry_price or 0.0

            # Place order
            order_id = await self._broker_adapter.place_limit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                price=price,
            )

            logger.info(
                "Agent %s: placed %s order %s for %d %s at $%.2f",
                self.agent_id, side.upper(), order_id, qty, ticker, price
            )

            # Record trade and update position tracking
            async with self._session_factory() as session:
                await self._record_trade(
                    session, parsed, qty, price, side, order_id, signal_dict
                )
                await session.commit()

            self._stats.trades_executed += 1

        except Exception as exc:
            logger.error(
                "Agent %s: trade execution failed for %s: %s",
                self.agent_id, ticker, exc, exc_info=True
            )
            self._stats.signals_skipped += 1

    async def _calculate_percentage_sell_qty(
        self,
        session,
        ticker: str,
        parsed,
        pct_value: int | str,
    ) -> int:
        """Calculate absolute quantity from percentage of open positions."""
        # Query current open/partially_closed positions
        result = await session.execute(
            select(func.sum(AgentTrade.current_quantity))
            .where(
                AgentTrade.agent_id == self.agent_id,
                AgentTrade.ticker == ticker,
                AgentTrade.strike == parsed.strike,
                AgentTrade.expiry == parsed.expiry,
                AgentTrade.position_status.in_(["open", "partially_closed"]),
            )
        )
        total_qty = result.scalar() or 0

        # Parse percentage (e.g., "50%" or 50)
        if isinstance(pct_value, str):
            pct_str = pct_value.replace("%", "").strip()
            try:
                pct = float(pct_str)
            except ValueError:
                pct = 100.0
        else:
            pct = float(pct_value)

        absolute_qty = int((pct / 100.0) * total_qty)
        logger.info(
            "Agent %s: %s%% of %d open contracts for %s = %d to sell",
            self.agent_id, pct, total_qty, ticker, absolute_qty
        )
        return absolute_qty

    async def _record_trade(
        self,
        session,
        parsed,
        qty: int,
        price: float,
        side: str,
        order_id: str,
        signal_dict: dict,
    ) -> None:
        """Record trade in DB and update position tracking."""
        ticker = parsed.ticker

        if side == "buy":
            # New position: create AgentTrade row
            trade = AgentTrade(
                agent_id=self.agent_id,
                ticker=ticker,
                side="BUY",
                option_type=parsed.option_type,
                strike=parsed.strike,
                expiry=parsed.expiry,
                entry_price=price,
                quantity=qty,
                current_quantity=qty,
                position_status="open",
                entry_time=datetime.now(timezone.utc),
                broker_order_id=order_id,
                signal_raw=signal_dict.get("raw_content"),
                model_confidence=signal_dict.get("confidence"),
            )
            session.add(trade)
            logger.info(
                "Agent %s: created new position for %s (qty=%d)",
                self.agent_id, ticker, qty
            )

        elif side == "sell":
            # Close or partially close existing positions (FIFO)
            result = await session.execute(
                select(AgentTrade)
                .where(
                    AgentTrade.agent_id == self.agent_id,
                    AgentTrade.ticker == ticker,
                    AgentTrade.strike == parsed.strike,
                    AgentTrade.expiry == parsed.expiry,
                    AgentTrade.position_status.in_(["open", "partially_closed"]),
                )
                .order_by(AgentTrade.entry_time)
            )
            positions = result.scalars().all()

            remaining_to_sell = qty
            for pos in positions:
                if remaining_to_sell <= 0:
                    break

                qty_to_close = min(pos.current_quantity, remaining_to_sell)
                new_current_qty = pos.current_quantity - qty_to_close

                # Update position
                pos.current_quantity = new_current_qty
                if new_current_qty == 0:
                    pos.position_status = "closed"
                    pos.exit_time = datetime.now(timezone.utc)
                    pos.exit_price = price
                    # Calculate PnL
                    if pos.entry_price:
                        pnl_dollar = (price - pos.entry_price) * qty_to_close * 100
                        pnl_pct = ((price - pos.entry_price) / pos.entry_price) * 100
                        pos.pnl_dollar = pnl_dollar
                        pos.pnl_pct = pnl_pct
                else:
                    pos.position_status = "partially_closed"

                remaining_to_sell -= qty_to_close

                logger.info(
                    "Agent %s: closed %d of %s (position_status=%s, current_qty=%d)",
                    self.agent_id, qty_to_close, ticker, pos.position_status, new_current_qty
                )

            if remaining_to_sell > 0:
                logger.warning(
                    "Agent %s: tried to sell %d %s but only had %d open",
                    self.agent_id, qty, ticker, qty - remaining_to_sell
                )

    async def _maybe_heartbeat(self) -> None:
        """Write heartbeat to DB at configured interval."""
        now = time.monotonic()
        if now - self._stats.last_heartbeat < settings.HEARTBEAT_INTERVAL_SEC:
            return
        self._stats.last_heartbeat = now

        try:
            async with self._session_factory() as session:
                utcnow = datetime.now(timezone.utc)
                await session.execute(
                    update(Agent)
                    .where(Agent.id == self.agent_id)
                    .values(last_activity_at=utcnow)
                )
                await session.execute(
                    update(PipelineWorkerState)
                    .where(PipelineWorkerState.agent_id == self.agent_id)
                    .values(
                        last_heartbeat=utcnow,
                        signals_processed=self._stats.signals_processed,
                        trades_executed=self._stats.trades_executed,
                        signals_skipped=self._stats.signals_skipped,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Heartbeat write failed for %s: %s", self.agent_id, exc)

    def stop(self) -> None:
        """Signal the worker to stop on next iteration."""
        self._running = False
