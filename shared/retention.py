"""
DEPRECATED — V3 removed the V2 models (NotificationLog, RawMessage, TradeEvent)
this module referenced. Kept for reference only. Do not use in new code.

Original purpose: Data retention policy — archive and purge old records.
"""

import logging
import warnings
from datetime import datetime, timedelta, timezone

warnings.warn(
    "shared.retention is deprecated — V3 removed the models it referenced.",
    DeprecationWarning,
    stacklevel=2,
)

try:
    from sqlalchemy import delete, func, select

    from shared.db.engine import async_session as AsyncSessionLocal
    # V1 models no longer exist — stubs for type reference only
    NotificationLog = None
    RawMessage = None
    TradeEvent = None
except ImportError:
    pass

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = {
    "trade_events": 90,
    "notification_log": 60,
    "raw_messages": 30,
}


async def purge_old_records(retention_days: dict[str, int] | None = None) -> dict[str, int]:
    """Delete rows older than the configured retention window.

    Returns a dict mapping table name to number of rows deleted.
    """
    config = retention_days or DEFAULT_RETENTION_DAYS
    results: dict[str, int] = {}

    table_map = {
        "trade_events": (TradeEvent, TradeEvent.created_at),
        "notification_log": (NotificationLog, NotificationLog.created_at),
        "raw_messages": (RawMessage, RawMessage.created_at),
    }

    async with AsyncSessionLocal() as session:
        for table_name, (model, date_col) in table_map.items():
            days = config.get(table_name, 90)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            count_result = await session.execute(
                select(func.count()).select_from(model).where(date_col < cutoff)
            )
            count = count_result.scalar() or 0

            if count > 0:
                await session.execute(
                    delete(model).where(date_col < cutoff)
                )
                logger.info("Purged %d rows from %s (older than %d days)", count, table_name, days)

            results[table_name] = count

        await session.commit()

    return results


async def get_retention_stats() -> dict[str, dict]:
    """Return row counts and oldest record age per table."""
    table_map = {
        "trade_events": (TradeEvent, TradeEvent.created_at),
        "notification_log": (NotificationLog, NotificationLog.created_at),
        "raw_messages": (RawMessage, RawMessage.created_at),
    }

    stats: dict[str, dict] = {}
    async with AsyncSessionLocal() as session:
        for table_name, (model, date_col) in table_map.items():
            total = (await session.execute(
                select(func.count()).select_from(model)
            )).scalar() or 0

            oldest = (await session.execute(
                select(func.min(date_col))
            )).scalar()

            retention = DEFAULT_RETENTION_DAYS.get(table_name, 90)

            stats[table_name] = {
                "total_rows": total,
                "oldest_record": oldest.isoformat() if oldest else None,
                "retention_days": retention,
            }

    return stats
