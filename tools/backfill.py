"""Discord message backfill tool with rate limiting, checkpointing, and resumability.

Usage:
    python -m tools.backfill --connector-id <uuid> --channel-id <snowflake> \\
      [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--batch-size 500] \\
      [--checkpoint backfill-checkpoint.json] [--resume]

Fetches historical messages from Discord API and inserts them into channel_messages.
Features:
- Rate limiting (leaky bucket + 429 handling)
- Resumable (checkpoint saved after each batch)
- Idempotent (skips duplicates via platform_message_id check)
- Signal-safe (SIGINT/SIGTERM flush + checkpoint + exit 130)
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from shared.db.models.channel_message import ChannelMessage
from shared.db.models.connector import Connector
from shared.discord_utils.rate_limiter import DiscordRateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# Global flag for graceful shutdown
_shutdown_requested = False


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGINT/SIGTERM by setting shutdown flag."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.warning(f"Received {sig_name} — will flush batch and exit after current commit")
    _shutdown_requested = True


class BackfillCheckpoint:
    """Manages checkpointing state for resumable backfill runs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}

    def load(self) -> dict:
        """Load checkpoint from disk."""
        if not self.path.exists():
            return {}
        with open(self.path) as f:
            self.data = json.load(f)
        return self.data

    def save(self, data: dict) -> None:
        """Save checkpoint to disk."""
        self.data = data
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.debug(f"Checkpoint saved: {data.get('messages_imported', 0)} messages, status={data.get('status')}")

    def update(self, **kwargs) -> None:
        """Update and save checkpoint."""
        self.data.update(kwargs)
        self.data["last_checkpoint_at"] = datetime.utcnow().isoformat()
        self.save(self.data)


class DiscordBackfiller:
    """Backfill Discord channel messages with rate limiting and resumability."""

    DISCORD_API_BASE = "https://discord.com/api/v10"
    DISCORD_PAGE_SIZE = 100  # Discord max per request

    def __init__(
        self,
        connector_id: uuid.UUID,
        channel_id: str,
        db_url: str,
        start_date: datetime,
        end_date: datetime,
        batch_size: int,
        checkpoint_path: Path,
        resume: bool,
    ) -> None:
        self.connector_id = connector_id
        self.channel_id = channel_id
        self.db_url = db_url
        self.start_date = start_date
        self.end_date = end_date
        self.batch_size = batch_size
        self.checkpoint_path = checkpoint_path
        self.resume = resume

        self.engine = create_engine(db_url, pool_pre_ping=True)
        self.rate_limiter = DiscordRateLimiter()
        self.checkpoint = BackfillCheckpoint(checkpoint_path)

        self.run_id: uuid.UUID = uuid.uuid4()
        self.last_message_id: Optional[str] = None
        self.messages_imported: int = 0
        self.batches_committed: int = 0
        self.current_batch: list[dict] = []

    def _decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt Discord bot token from connector credentials."""
        encryption_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
        if not encryption_key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY not set in environment")

        cipher = Fernet(encryption_key.encode())
        decrypted = cipher.decrypt(encrypted_token.encode())
        credentials = json.loads(decrypted)
        token = credentials.get("bot_token") or credentials.get("token")
        if not token:
            raise ValueError("No bot_token or token found in decrypted credentials")
        return token

    def _load_connector(self) -> Connector:
        """Load connector from database and validate."""
        with Session(self.engine) as session:
            stmt = select(Connector).where(Connector.id == self.connector_id)
            connector = session.execute(stmt).scalar_one_or_none()
            if not connector:
                raise ValueError(f"Connector {self.connector_id} not found")
            if connector.type != "discord":
                raise ValueError(f"Connector {self.connector_id} is not type=discord (got {connector.type})")
            if not connector.credentials_encrypted:
                raise ValueError(f"Connector {self.connector_id} has no credentials_encrypted")
            return connector

    def _init_checkpoint(self) -> None:
        """Initialize or resume from checkpoint."""
        if self.resume:
            cp = self.checkpoint.load()
            if cp:
                logger.info(
                    f"Resuming from checkpoint: run_id={cp['run_id']}, "
                    f"last_message_id={cp.get('last_message_id')}"
                )
                self.run_id = uuid.UUID(cp["run_id"])
                self.last_message_id = cp.get("last_message_id")
                self.messages_imported = cp.get("messages_imported", 0)
                self.batches_committed = cp.get("batches_committed", 0)
                return

        # Fresh run
        self.checkpoint.save({
            "run_id": str(self.run_id),
            "connector_id": str(self.connector_id),
            "channel_id": self.channel_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "last_message_id": None,
            "messages_imported": 0,
            "batches_committed": 0,
            "last_checkpoint_at": datetime.utcnow().isoformat(),
            "status": "in_progress",
        })
        logger.info(f"Started new backfill run: run_id={self.run_id}")

    def _is_duplicate(self, platform_message_id: str, session: Session) -> bool:
        """Check if message already exists in DB (idempotency)."""
        stmt = select(ChannelMessage.id).where(
            ChannelMessage.platform_message_id == platform_message_id
        ).limit(1)
        exists = session.execute(stmt).scalar_one_or_none()
        return exists is not None

    def _flush_batch(self, session: Session) -> None:
        """Commit current batch to database."""
        if not self.current_batch:
            return

        # Filter out duplicates
        unique_batch = []
        for msg_dict in self.current_batch:
            if not self._is_duplicate(msg_dict["platform_message_id"], session):
                unique_batch.append(msg_dict)
            else:
                logger.debug(f"Skipping duplicate message: {msg_dict['platform_message_id']}")

        if unique_batch:
            # Check if backfill_run_id column exists (added in migration 046)
            has_backfill_column = True
            try:
                # Try to inspect if column exists via a simple query
                session.execute(select(ChannelMessage.id).limit(0))
                # Check if backfill_run_id is in the model's columns
                has_column = (
                    hasattr(ChannelMessage, '__table__')
                    and 'backfill_run_id' in [c.name for c in ChannelMessage.__table__.columns]
                )
                if not has_column:
                    has_backfill_column = False
                    logger.warning(
                        "backfill_run_id column not found in channel_messages — "
                        "skipping field (run migration 046)"
                    )
            except Exception:
                has_backfill_column = False

            if has_backfill_column:
                for msg in unique_batch:
                    msg["backfill_run_id"] = self.run_id

            session.bulk_insert_mappings(ChannelMessage, unique_batch)
            session.commit()

            self.messages_imported += len(unique_batch)
            self.batches_committed += 1

            logger.info(
                f"Batch {self.batches_committed} committed: {len(unique_batch)} messages "
                f"(total: {self.messages_imported:,})"
            )

        self.current_batch.clear()

        # Update checkpoint
        self.checkpoint.update(
            last_message_id=self.last_message_id,
            messages_imported=self.messages_imported,
            batches_committed=self.batches_committed,
        )

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        before: Optional[str] = None,
    ) -> list[dict]:
        """Fetch a single page of messages from Discord API."""
        url = f"{self.DISCORD_API_BASE}/channels/{self.channel_id}/messages"
        params = {"limit": self.DISCORD_PAGE_SIZE}
        if before:
            params["before"] = before

        await self.rate_limiter.wait_if_needed(self.channel_id)

        try:
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after")
                await self.rate_limiter.handle_429(self.channel_id, retry_after)
                # Retry after rate limit delay
                return await self._fetch_page(client, headers, before)

            if resp.status_code != 200:
                logger.error(f"Discord API error {resp.status_code}: {resp.text[:200]}")
                return []

            self.rate_limiter.mark_success(self.channel_id)
            return resp.json()

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            logger.error(f"Discord API connection error: {exc}")
            return []

    def _parse_discord_message(self, msg: dict) -> dict:
        """Parse Discord API message into ChannelMessage format."""
        timestamp_str = msg["timestamp"]
        posted_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

        return {
            "connector_id": self.connector_id,
            "channel": self.channel_id,  # Legacy column (will be replaced by channel_id_snowflake in migration 046)
            "author": msg["author"].get("username", "unknown"),
            "content": msg.get("content", ""),
            "message_type": "unknown",
            "tickers_mentioned": [],
            "raw_data": msg,
            "platform_message_id": msg["id"],
            "posted_at": posted_at,
        }

    async def run(self) -> None:
        """Execute the backfill operation."""
        # Install signal handlers
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        # Load connector and decrypt token
        connector = self._load_connector()
        token = self._decrypt_token(connector.credentials_encrypted)
        headers = {"Authorization": f"Bot {token}"}

        # Initialize checkpoint
        self._init_checkpoint()

        # Start fetching
        before = self.last_message_id
        async with httpx.AsyncClient(timeout=30.0) as client:
            with Session(self.engine) as session:
                while not _shutdown_requested:
                    batch = await self._fetch_page(client, headers, before)

                    if not batch:
                        logger.info("No more messages returned by Discord API")
                        break

                    for msg in batch:
                        posted_at = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))

                        # Stop if we've gone past the start date
                        if posted_at < self.start_date:
                            logger.info(f"Reached start_date boundary: {self.start_date.isoformat()}")
                            self._flush_batch(session)
                            self.checkpoint.update(status="completed")
                            logger.info(
                                f"Backfill completed: {self.messages_imported:,} messages, "
                                f"{self.batches_committed} batches"
                            )
                            return

                        # Stop if message is after end date
                        if posted_at > self.end_date:
                            continue

                        # Add to batch
                        msg_dict = self._parse_discord_message(msg)
                        self.current_batch.append(msg_dict)
                        self.last_message_id = msg["id"]

                        # Flush if batch is full
                        if len(self.current_batch) >= self.batch_size:
                            self._flush_batch(session)

                            if _shutdown_requested:
                                break

                    # Move to next page
                    if len(batch) < self.DISCORD_PAGE_SIZE:
                        logger.info("Fetched last page (fewer than 100 messages)")
                        break

                    before = batch[-1]["id"]

                # Final flush
                self._flush_batch(session)

                if _shutdown_requested:
                    logger.warning("Backfill interrupted by signal — checkpoint saved")
                    sys.exit(130)

                self.checkpoint.update(status="completed")
                logger.info(
                    f"Backfill completed: {self.messages_imported:,} messages imported, "
                    f"{self.batches_committed} batches committed"
                )

                # Print rate limit stats
                stats = self.rate_limiter.get_stats(self.channel_id)
                logger.info(f"Rate limit stats: {stats}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Discord channel messages into channel_messages table"
    )
    parser.add_argument("--connector-id", required=True, help="Connector UUID")
    parser.add_argument("--channel-id", required=True, help="Discord channel snowflake")
    parser.add_argument(
        "--from",
        dest="start_date",
        help="Start date (YYYY-MM-DD, default: 730 days ago)",
    )
    parser.add_argument(
        "--to",
        dest="end_date",
        help="End date (YYYY-MM-DD, default: now)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Messages per batch commit (default: 500)",
    )
    parser.add_argument(
        "--checkpoint",
        default="backfill-checkpoint.json",
        help="Checkpoint file path (default: backfill-checkpoint.json)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoint",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="Database URL (default: DATABASE_URL env var)",
    )
    args = parser.parse_args()

    if not args.db_url:
        parser.error("--db-url required or set DATABASE_URL environment variable")

    # Parse dates
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_date = datetime.now(timezone.utc) - timedelta(days=730)

    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end_date = datetime.now(timezone.utc)

    logger.info(
        f"Starting backfill: connector={args.connector_id}, channel={args.channel_id}, "
        f"date_range={start_date.date()} to {end_date.date()}"
    )

    backfiller = DiscordBackfiller(
        connector_id=uuid.UUID(args.connector_id),
        channel_id=args.channel_id,
        db_url=args.db_url,
        start_date=start_date,
        end_date=end_date,
        batch_size=args.batch_size,
        checkpoint_path=Path(args.checkpoint),
        resume=args.resume,
    )

    asyncio.run(backfiller.run())


if __name__ == "__main__":
    main()
