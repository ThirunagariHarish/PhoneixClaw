"""Phase B observability metrics — shared Prometheus registry and metric helpers.

Provides:
- tool_latency_histogram — phoenix_tool_duration_seconds{tool}
- agent_session_counter — phoenix_agent_sessions_created_total
- subagent_spawn_counter — phoenix_subagent_spawned_total
- circuit_breaker_gauge — phoenix_circuit_breaker_state_by_name{name} (0=closed, 1=half_open, 2=open)
- dlq_size_gauge — phoenix_dlq_unresolved_total{connector_id}
- stream_lag_gauge — phoenix_redis_stream_lag_seconds{stream_key}
- discord_messages_counter — phoenix_discord_messages_total

Phase B wave 3 additions:
- Background async refresher task that keeps dlq_size_gauge fresh without making the
  `/metrics` scrape do a synchronous DB query (15s refresh interval).

Note: phoenix_trades_total already exists in shared.metrics.TRADE_COUNTER with {service, status} labels.
We reuse it for tool-side trade metrics.
"""

import asyncio
import logging
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.metrics import TRADE_COUNTER as trade_success_counter
from shared.metrics import registry

logger = logging.getLogger(__name__)

# Tool latency across parse_signal, enrich_single, inference, risk_check, technical_analysis, execute_trade
tool_latency_histogram = Histogram(
    "phoenix_tool_duration_seconds",
    "Duration of agent tool calls in seconds",
    ["tool"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    registry=registry,
)

# Agent session creation (primary, position_monitor, supervisor, etc.)
agent_session_counter = Counter(
    "phoenix_agent_sessions_created_total",
    "Agent sessions created",
    registry=registry,
)

# Sub-agent spawn count (position monitors)
subagent_spawn_counter = Counter(
    "phoenix_subagent_spawned_total",
    "Sub-agents spawned (position monitors)",
    registry=registry,
)

# Circuit breaker state gauge with "name" label (0=closed, 1=half_open, 2=open)
# Note: shared.metrics.CIRCUIT_BREAKER_STATE uses "service" label; we need "name" label for tool-side.
circuit_breaker_gauge = Gauge(
    "phoenix_circuit_breaker_state_by_name",
    "Circuit breaker state: 0=closed, 1=half_open, 2=open",
    ["name"],
    registry=registry,
)

# DLQ size (unresolved messages per connector)
dlq_size_gauge = Gauge(
    "phoenix_dlq_unresolved_total",
    "Unresolved dead letter messages by connector",
    ["connector_id"],
    registry=registry,
)

# Redis stream lag (seconds behind latest entry)
stream_lag_gauge = Gauge(
    "phoenix_redis_stream_lag_seconds",
    "Redis stream lag in seconds",
    ["stream_key"],
    registry=registry,
)

# Discord messages ingested
discord_messages_counter = Counter(
    "phoenix_discord_messages_total",
    "Discord messages persisted to DB and Redis",
    registry=registry,
)

# DB connection pool capacity + utilisation (gauges; refreshed on each /metrics scrape)
db_pool_size_gauge = Gauge(
    "phoenix_db_pool_size",
    "SQLAlchemy connection pool: total slots configured (pool_size + max_overflow)",
    registry=registry,
)
db_pool_checked_in_gauge = Gauge(
    "phoenix_db_pool_checked_in",
    "Connections currently idle in pool (available for checkout)",
    registry=registry,
)
db_pool_checked_out_gauge = Gauge(
    "phoenix_db_pool_checked_out",
    "Connections currently in use by request handlers",
    registry=registry,
)
db_pool_overflow_gauge = Gauge(
    "phoenix_db_pool_overflow",
    "Connections beyond pool_size that have been opened (closes when returned)",
    registry=registry,
)


def refresh_db_pool_gauges() -> None:
    """Snapshot the SQLAlchemy QueuePool stats into Prometheus gauges.

    Cheap (in-memory accessors). Called from the /metrics handler so the gauges
    reflect the live pool at scrape time. Safe if pool isn't initialised yet.
    """
    try:
        from shared.db.engine import get_engine
        eng = get_engine()
        pool = eng.pool
        # Size = configured pool_size + observed overflow ceiling
        size = pool.size() if hasattr(pool, "size") else 0
        checked_out = pool.checkedout() if hasattr(pool, "checkedout") else 0
        # checkedin() returns the count of idle conns; overflow() returns extra opened
        checked_in = pool.checkedin() if hasattr(pool, "checkedin") else 0
        overflow = pool.overflow() if hasattr(pool, "overflow") else 0
        db_pool_size_gauge.set(size)
        db_pool_checked_in_gauge.set(checked_in)
        db_pool_checked_out_gauge.set(checked_out)
        db_pool_overflow_gauge.set(max(0, overflow))
    except Exception:
        # Never crash /metrics on pool inspection failure
        pass


# --- DLQ gauge background refresher (Phase B wave 3) ----------------------
# Keeps dlq_size_gauge fresh without a synchronous DB query on every /metrics scrape.

_dlq_refresh_task: Optional[asyncio.Task] = None
_dlq_refresh_running = False


async def _refresh_dlq_gauge() -> None:
    """Background task that refreshes the DLQ gauge every 15s.

    Queries `dead_letter_messages` for unresolved counts per connector_id and updates
    the Prometheus gauge. Runs until `stop_dlq_gauge_refresher()` is called.
    """
    global _dlq_refresh_running

    try:
        from shared.db.engine import get_async_session_maker
        session_maker = get_async_session_maker()
    except Exception as e:
        logger.warning(f"DLQ gauge refresher disabled — cannot load DB session: {e}")
        return

    _dlq_refresh_running = True
    logger.info("Starting DLQ gauge background refresher (15s interval)")

    while _dlq_refresh_running:
        try:
            async with session_maker() as session:
                session: AsyncSession
                query = text(
                    "SELECT connector_id, COUNT(*) as count "
                    "FROM dead_letter_messages "
                    "WHERE resolved = false "
                    "GROUP BY connector_id"
                )
                result = await session.execute(query)
                rows = result.fetchall()
                dlq_size_gauge._metrics.clear()
                for connector_id, count in rows:
                    dlq_size_gauge.labels(connector_id=connector_id).set(count)
                logger.debug(f"Refreshed DLQ gauge: {len(rows)} connector(s)")
        except Exception as e:
            logger.error(f"Failed to refresh DLQ gauge: {e}")

        await asyncio.sleep(15)


def start_dlq_gauge_refresher() -> None:
    """Start the background DLQ gauge refresh task.

    Safe to call multiple times — only starts once. Should be called on app startup
    (e.g., FastAPI lifespan or startup event).
    """
    global _dlq_refresh_task

    if _dlq_refresh_task is not None and not _dlq_refresh_task.done():
        logger.debug("DLQ gauge refresher already running")
        return

    try:
        _dlq_refresh_task = asyncio.create_task(_refresh_dlq_gauge())
        logger.info("DLQ gauge refresher task started")
    except RuntimeError:
        logger.warning("DLQ gauge refresher not started — no running asyncio loop")


def stop_dlq_gauge_refresher() -> None:
    """Stop the background DLQ gauge refresh task.

    Should be called on app shutdown.
    """
    global _dlq_refresh_running, _dlq_refresh_task

    if _dlq_refresh_task is None or _dlq_refresh_task.done():
        logger.debug("DLQ gauge refresher not running")
        return

    _dlq_refresh_running = False
    _dlq_refresh_task.cancel()
    logger.info("DLQ gauge refresher task stopped")


__all__ = [
    "tool_latency_histogram",
    "trade_success_counter",
    "agent_session_counter",
    "subagent_spawn_counter",
    "circuit_breaker_gauge",
    "dlq_size_gauge",
    "stream_lag_gauge",
    "discord_messages_counter",
    "start_dlq_gauge_refresher",
    "stop_dlq_gauge_refresher",
]
