"""Shared Prometheus metrics registry and helpers.

Provides centralized metrics for Phase B observability:
- phoenix_dlq_size: gauge tracking unresolved DLQ entries (refreshed every 15s)
- Background refresher task to avoid synchronous DB queries in /metrics scrape
"""

import asyncio
import logging
from typing import Optional

from prometheus_client import CollectorRegistry, Gauge
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_async_session_maker

logger = logging.getLogger(__name__)

# Shared registry for all Phoenix metrics
phoenix_registry = CollectorRegistry()

# DLQ size gauge — tracks unresolved entries per connector_id
phoenix_dlq_size = Gauge(
    "phoenix_dlq_unresolved_total",
    "Number of unresolved dead letter messages",
    labelnames=["connector_id"],
    registry=phoenix_registry,
)

# Background refresh state
_dlq_refresh_task: Optional[asyncio.Task] = None
_dlq_refresh_running = False


async def _refresh_dlq_gauge() -> None:
    """Background task that refreshes DLQ gauge every 15s.

    Queries DB for unresolved counts per connector_id and updates Prometheus gauge.
    Runs indefinitely until cancelled.
    """
    global _dlq_refresh_running
    _dlq_refresh_running = True
    session_maker = get_async_session_maker()

    logger.info("Starting DLQ gauge background refresher (15s interval)")

    while _dlq_refresh_running:
        try:
            async with session_maker() as session:
                session: AsyncSession
                # Query unresolved counts grouped by connector_id
                query = text(
                    "SELECT connector_id, COUNT(*) as count "
                    "FROM dead_letter_messages "
                    "WHERE resolved = false "
                    "GROUP BY connector_id"
                )
                result = await session.execute(query)
                rows = result.fetchall()

                # Clear previous labels and set new values
                phoenix_dlq_size._metrics.clear()
                for connector_id, count in rows:
                    phoenix_dlq_size.labels(connector_id=connector_id).set(count)

                logger.debug(f"Refreshed DLQ gauge: {len(rows)} connector(s)")

        except Exception as e:
            logger.error(f"Failed to refresh DLQ gauge: {e}")

        await asyncio.sleep(15)


def start_dlq_gauge_refresher() -> None:
    """Start the background DLQ gauge refresh task.

    Safe to call multiple times — only starts once.
    Should be called on app startup.
    """
    global _dlq_refresh_task

    if _dlq_refresh_task is not None and not _dlq_refresh_task.done():
        logger.debug("DLQ gauge refresher already running")
        return

    _dlq_refresh_task = asyncio.create_task(_refresh_dlq_gauge())
    logger.info("DLQ gauge refresher task started")


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
