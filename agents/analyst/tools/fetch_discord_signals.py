"""Fetch recent Discord/UW trade signals from the database."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def fetch_discord_signals(
    agent_id: str | None = None,
    since_minutes: int = 30,
    db_url: str | None = None,
) -> list[dict]:
    """Fetch recent Discord/UW signals from the trade_signals table.

    Filters on signal_source IN ('discord', 'unusual_whales') and
    created_at >= now() - since_minutes.

    Args:
        agent_id: Optional agent UUID to scope signals (not filtered, but logged).
        since_minutes: How many minutes back to look.
        db_url: Database URL. Falls back to DATABASE_URL env var.

    Returns:
        List of dicts with ticker, direction, features, created_at.
    """
    url = db_url or os.environ.get("DATABASE_URL", "")
    if not url:
        logger.warning("fetch_discord_signals: DATABASE_URL not set — returning empty list")
        return []

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import NullPool

        # Convert sync postgres:// URLs to async
        async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgres://", "postgresql+asyncpg://"
        )

        # NullPool: no connection pooling — correct for short-lived subprocess tools
        engine = create_async_engine(async_url, echo=False, pool_pre_ping=True, poolclass=NullPool)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT id, ticker, direction, signal_source, features, created_at
                    FROM trade_signals
                    WHERE signal_source IN ('discord', 'unusual_whales')
                      AND created_at >= :cutoff
                    ORDER BY created_at DESC
                    LIMIT 200
                """),
                {"cutoff": cutoff},
            )
            rows = result.fetchall()

        await engine.dispose()

        signals = []
        for row in rows:
            signals.append({
                "id": str(row[0]),
                "ticker": row[1],
                "direction": row[2],
                "signal_source": row[3],
                "features": row[4] if isinstance(row[4], dict) else {},
                "created_at": row[5].isoformat() if row[5] else None,
            })

        logger.info("fetch_discord_signals: found %d signals in last %d min", len(signals), since_minutes)
        return signals

    except Exception as exc:
        logger.warning("fetch_discord_signals error: %s", exc)
        return []


async def _main_async(args: argparse.Namespace) -> None:
    signals = await fetch_discord_signals(
        since_minutes=args.since_minutes,
        db_url=args.db_url,
    )
    print(json.dumps(signals, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch recent Discord/UW signals from DB")
    parser.add_argument("--since-minutes", type=int, default=30, help="Look back N minutes")
    parser.add_argument("--db-url", default=None, help="Database URL (defaults to DATABASE_URL env)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))
