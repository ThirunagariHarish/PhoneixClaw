"""
Orchestrator service entrypoint — routes events from Redis streams
to the appropriate handlers.

M2.1: Central orchestration layer.

Phase 15.8 additions
--------------------
- Reads ``PM_TOP_BETS_ENABLED`` (default: ``"true"``) and ``PM_TOP_BETS_VENUE``
  (default: ``"robinhood_predictions"``) env vars.
- When enabled, constructs a :class:`~agents.polymarket.top_bets.agent.TopBetsAgent`
  wrapped in a :class:`~services.orchestrator.src.pm_agent_runtime.PMAgentRuntime`
  and starts it as a background asyncio task alongside the stream-poll loop.
- Registers the runtime with ``register_pm_runtime`` so the existing
  kill-switch fan-out handler can trip/rearm the agent.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI
from prometheus_client import Counter, Gauge, generate_latest
from starlette.responses import Response

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

events_processed = Counter(
    "orchestrator_events_processed_total",
    "Total events processed by stream",
    ["stream"],
)
active_polls = Gauge("orchestrator_active_polls", "Currently active poll loops")

_shutdown_event = asyncio.Event()


async def _get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


async def handle_trade_intent(entry_id: str, data: dict[str, Any]) -> None:
    logger.info("Trade intent %s: %s %s %s",
                entry_id, data.get("side"), data.get("qty"), data.get("symbol"))
    events_processed.labels(stream="trade-intents").inc()


async def handle_agent_event(entry_id: str, data: dict[str, Any]) -> None:
    event_type = data.get("type", "unknown")
    agent_id = data.get("agent_id", "?")
    logger.info("Agent event %s from %s: %s", event_type, agent_id, entry_id)
    events_processed.labels(stream="agent-events").inc()


# B2: kill-switch fan-out — any registered PMAgentRuntime is tripped/rearmed
# when an event lands on stream:kill-switch.
PM_RUNTIMES: list[Any] = []


def register_pm_runtime(runtime: Any) -> None:
    PM_RUNTIMES.append(runtime)


async def handle_kill_switch(entry_id: str, data: dict[str, Any]) -> None:
    action = (data.get("action") or data.get("type") or "").lower()
    reason = str(data.get("reason", "stream"))
    logger.warning("orchestrator kill-switch event %s action=%s reason=%s", entry_id, action, reason)
    for rt in PM_RUNTIMES:
        try:
            if action in ("activate", "trip", "halt", "kill"):
                rt.trip(reason=reason)
            elif action in ("deactivate", "rearm", "clear"):
                rt.rearm()
        except Exception:
            logger.exception("pm runtime kill-switch dispatch failed")
    events_processed.labels(stream="kill-switch").inc()


STREAM_HANDLERS: dict[str, Any] = {
    "stream:trade-intents": handle_trade_intent,
    "stream:agent-events": handle_agent_event,
    "stream:kill-switch": handle_kill_switch,
}


async def _poll_streams(r: redis.Redis) -> None:
    """Long-poll Redis streams and dispatch to handlers."""
    last_ids: dict[str, str] = {s: "$" for s in STREAM_HANDLERS}

    active_polls.inc()
    try:
        while not _shutdown_event.is_set():
            try:
                streams = {name: last_ids[name] for name in STREAM_HANDLERS}
                results = await r.xread(streams, count=50, block=2000)

                for stream_name, entries in results:
                    handler = STREAM_HANDLERS.get(stream_name)
                    if not handler:
                        continue
                    for entry_id, data in entries:
                        try:
                            await handler(entry_id, data)
                        except Exception:
                            logger.exception("Handler error for %s/%s", stream_name, entry_id)
                        last_ids[stream_name] = entry_id

            except redis.ConnectionError:
                logger.warning("Redis connection lost, retrying in 3s")
                await asyncio.sleep(3)
    finally:
        active_polls.dec()


@asynccontextmanager
async def lifespan(app: FastAPI):
    r = await _get_redis()
    poll_task = asyncio.create_task(_poll_streams(r))
    logger.info("Orchestrator stream polling started")

    # ------------------------------------------------------------------
    # Phase 15.8: Start TopBetsAgent if enabled
    # ------------------------------------------------------------------
    _top_bets_task: asyncio.Task | None = None
    _pm_runtime = None

    _pm_enabled = os.getenv("PM_TOP_BETS_ENABLED", "true").lower() == "true"
    if _pm_enabled:
        try:
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
            from sqlalchemy.orm import sessionmaker

            from agents.polymarket.top_bets.agent import TopBetsAgent
            from services.orchestrator.src.pm_agent_runtime import build_runtime

            _db_url = os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader",
            )
            _engine = create_async_engine(_db_url, echo=False, pool_pre_ping=True)
            _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

            _venue = os.getenv("PM_TOP_BETS_VENUE", "robinhood_predictions")
            _top_bets_agent = TopBetsAgent(
                db_session_factory=_session_factory,
                redis_url=REDIS_URL,
                venue_name=_venue,
            )
            _pm_runtime = build_runtime(agent=_top_bets_agent, redis_client=r)
            register_pm_runtime(_pm_runtime)
            _top_bets_task = asyncio.create_task(_pm_runtime.run())
            logger.info("pm_top_bets agent started (venue=%s)", _venue)
        except Exception:  # noqa: BLE001
            logger.exception("pm_top_bets agent failed to start — orchestrator continues without it")
    else:
        logger.info("pm_top_bets agent disabled (PM_TOP_BETS_ENABLED != true)")

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    _shutdown_event.set()
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass

    if _pm_runtime is not None:
        _pm_runtime.stop()
    if _top_bets_task is not None:
        _top_bets_task.cancel()
        try:
            await _top_bets_task
        except (asyncio.CancelledError, Exception):
            pass

    await r.aclose()
    logger.info("Orchestrator shutdown complete")


app = FastAPI(title="Orchestrator", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8042)
