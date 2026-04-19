"""Archive old channel messages to JSONL files with optional DB deletion.

Usage:
    python -m tools.archive_old_messages --before 2024-01-01 [--channel-id <id>] \\
      [--output archive.jsonl] [--delete-after-archive]

Archives messages older than the specified date to a JSONL file (one message per line).
Supports selective archival by channel_id. Optionally deletes archived messages from DB.

Features:
- Streaming output (low memory footprint)
- Idempotent (running twice produces identical output)
- Dry-run mode (no deletion by default)
- Progress reporting every 1000 messages
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from shared.db.models.channel_message import ChannelMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def archive_messages(
    db_url: str,
    before_date: datetime,
    channel_id: Optional[str],
    output_path: Path,
    delete_after_archive: bool,
) -> int:
    """Archive messages older than before_date to JSONL file.

    Args:
        db_url: PostgreSQL connection URL
        before_date: Archive messages posted before this datetime
        channel_id: Optional channel_id_snowflake filter
        output_path: Output JSONL file path
        delete_after_archive: If True, delete archived messages from DB

    Returns:
        Number of messages archived
    """
    engine = create_engine(db_url, echo=False)
    archived_count = 0
    archived_ids = []

    with Session(engine) as session:
        # Build query
        query = select(ChannelMessage).where(ChannelMessage.posted_at < before_date)
        if channel_id:
            query = query.where(ChannelMessage.channel_id_snowflake == channel_id)
        query = query.order_by(ChannelMessage.posted_at)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_count = session.scalar(count_query) or 0
        logger.info(f"Found {total_count:,} messages to archive")

        if total_count == 0:
            logger.info("No messages to archive")
            return 0

        # Stream to JSONL
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            for msg in session.execute(query).scalars():
                # Serialize to JSON
                msg_dict = {
                    "id": str(msg.id),
                    "connector_id": str(msg.connector_id),
                    "channel": msg.channel,
                    "channel_id_snowflake": msg.channel_id_snowflake,
                    "backfill_run_id": str(msg.backfill_run_id) if msg.backfill_run_id else None,
                    "author": msg.author,
                    "content": msg.content,
                    "message_type": msg.message_type,
                    "tickers_mentioned": msg.tickers_mentioned,
                    "raw_data": msg.raw_data,
                    "platform_message_id": msg.platform_message_id,
                    "posted_at": msg.posted_at.isoformat(),
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                f.write(json.dumps(msg_dict, default=str) + "\n")
                archived_count += 1
                archived_ids.append(msg.id)

                if archived_count % 1000 == 0:
                    logger.info(f"Archived {archived_count:,} / {total_count:,} messages")

        logger.info(f"Archived {archived_count:,} messages to {output_path}")

        # Delete if requested
        if delete_after_archive and archived_ids:
            logger.info(f"Deleting {len(archived_ids):,} archived messages from database...")
            delete_stmt = delete(ChannelMessage).where(ChannelMessage.id.in_(archived_ids))
            result = session.execute(delete_stmt)
            session.commit()
            logger.info(f"Deleted {result.rowcount:,} messages from database")

    return archived_count


def main():
    parser = argparse.ArgumentParser(
        description="Archive old channel messages to JSONL file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Archive all messages before 2024-01-01 (no deletion)
  python -m tools.archive_old_messages --before 2024-01-01 --output archive.jsonl

  # Archive and delete from specific channel
  python -m tools.archive_old_messages --before 2024-01-01 --channel-id 1234567890 \\
    --output archive-channel.jsonl --delete-after-archive

  # Archive last year's messages
  python -m tools.archive_old_messages --before 2025-01-01 --output archive-2024.jsonl
        """,
    )
    parser.add_argument(
        "--before",
        required=True,
        help="Archive messages posted before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--channel-id",
        help="Only archive messages from this channel_id_snowflake",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("archive.jsonl"),
        help="Output JSONL file path (default: archive.jsonl)",
    )
    parser.add_argument(
        "--delete-after-archive",
        action="store_true",
        help="Delete archived messages from database after writing to file",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql://phoenixtrader:localdev@localhost:5432/phoenixtrader",
        ),
        help="Database URL (default: from DATABASE_URL env var)",
    )

    args = parser.parse_args()

    # Parse date
    try:
        before_date = datetime.strptime(args.before, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Invalid date format: {args.before}. Expected YYYY-MM-DD")
        sys.exit(2)

    # Confirm deletion if requested
    if args.delete_after_archive:
        logger.warning("--delete-after-archive is enabled. Messages WILL be deleted from the database.")
        logger.warning(f"Archive target: messages before {args.before}")
        if args.channel_id:
            logger.warning(f"Channel filter: {args.channel_id}")
        response = input("Continue? [y/N]: ")
        if response.lower() != "y":
            logger.info("Aborted by user")
            sys.exit(0)

    try:
        count = archive_messages(
            db_url=args.db_url,
            before_date=before_date,
            channel_id=args.channel_id,
            output_path=args.output,
            delete_after_archive=args.delete_after_archive,
        )
        logger.info(f"✅ Archive complete: {count:,} messages")
        sys.exit(0)
    except Exception:
        logger.exception("Archive failed")
        sys.exit(2)


if __name__ == "__main__":
    main()
