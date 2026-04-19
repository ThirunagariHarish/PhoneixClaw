"""Single agent's Redis stream processing loop."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
from sqlalchemy import update

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
from shared.db.models.agent import Agent, PipelineWorkerState

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
    ) -> None:
        self.agent_id = agent_id
        self.connector_ids = connector_ids
        self.config = config
        self.redis = redis_client
        self._session_factory = session_factory
        self._stats = WorkerStats()
        self._inference = InferenceClient(
            inference_url=config.get("inference_service_url", settings.INFERENCE_SERVICE_URL),
        )
        self._running = False

        self._group_name = f"pipeline-{agent_id}"
        self._consumer_name = "worker-1"
        self._stream_keys = [f"stream:channel:{cid}" for cid in connector_ids]

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

    async def run(self) -> None:
        """Main loop: create consumer groups, then xreadgroup in a loop."""
        self._running = True

        for key in self._stream_keys:
            try:
                await self.redis.xgroup_create(key, self._group_name, id="0", mkstream=True)
                logger.info("Created consumer group %s on %s", self._group_name, key)
            except Exception:
                pass  # group already exists

        async with httpx.AsyncClient() as http_client:
            while self._running:
                try:
                    await self._read_and_process(http_client)
                    await self._maybe_heartbeat()
                except asyncio.CancelledError:
                    logger.info("Worker %s cancelled — shutting down", self.agent_id)
                    break
                except Exception as exc:
                    logger.error("Worker %s error: %s", self.agent_id, exc, exc_info=True)
                    await asyncio.sleep(2)

        self._running = False
        logger.info("Worker %s stopped", self.agent_id)

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
            intent = {
                "agent_id": self.agent_id,
                "symbol": decision.execution_params["symbol"],
                "side": decision.execution_params["side"],
                "qty": decision.execution_params["qty"],
                "order_type": decision.execution_params["order_type"],
                "confidence": decision.final_confidence,
                "signal_data": signal_dict,
                "source": "pipeline-worker",
            }
            await publisher.publish_trade_intent(self.redis, intent)
            self._stats.trades_executed += 1
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
