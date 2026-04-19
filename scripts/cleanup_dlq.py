"""Cleanup resolved DLQ entries older than N days.

Usage:
    python -m scripts.cleanup_dlq [--days 30] [--dry-run]

This script deletes resolved dead_letter_messages rows older than the specified
threshold to prevent unbounded growth (addresses Phase B risk B-R3).
Idempotent and safe to run repeatedly via cron.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_async_session_maker


async def cleanup_dlq(days: int, dry_run: bool) -> None:
    """Delete resolved DLQ rows older than threshold.

    Args:
        days: Delete rows resolved more than this many days ago
        dry_run: If True, only count rows; don't delete
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session_maker = get_async_session_maker()

    async with session_maker() as session:
        session: AsyncSession
        # Count matching rows
        count_query = text(
            "SELECT COUNT(*) FROM dead_letter_messages "
            "WHERE resolved = true AND resolved_at < :cutoff"
        )
        result = await session.execute(count_query, {"cutoff": cutoff})
        count = result.scalar_one()

        if dry_run:
            print(f"[DRY RUN] Would delete {count} resolved DLQ rows older than {days} days (cutoff: {cutoff})")
            return

        if count == 0:
            print(f"No resolved DLQ rows older than {days} days to delete")
            return

        # Delete matching rows
        delete_query = text(
            "DELETE FROM dead_letter_messages "
            "WHERE resolved = true AND resolved_at < :cutoff"
        )
        await session.execute(delete_query, {"cutoff": cutoff})
        await session.commit()

        print(f"Deleted {count} resolved DLQ rows older than {days} days (cutoff: {cutoff})")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Cleanup resolved DLQ entries older than N days")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Delete rows resolved more than this many days ago (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count matching rows; don't delete",
    )
    args = parser.parse_args()

    if args.days < 1:
        print("Error: --days must be >= 1", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(cleanup_dlq(args.days, args.dry_run))
    except Exception as e:
        print(f"Error during DLQ cleanup: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
