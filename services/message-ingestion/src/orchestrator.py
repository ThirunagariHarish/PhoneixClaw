"""
Ingestion orchestrator — coordinates pulling historical messages from a connector,
storing them in the channel_messages table, and tracking progress.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.channel_message import ChannelMessage
from .base_adapter import BaseMessageAdapter
from .discord_adapter import DiscordAdapter
from .reddit_adapter import RedditAdapter
from .twitter_adapter import TwitterAdapter

logger = logging.getLogger(__name__)

ADAPTER_MAP: dict[str, type[BaseMessageAdapter]] = {
    "discord": DiscordAdapter,
    "reddit": RedditAdapter,
    "twitter": TwitterAdapter,
}


async def ingest_history(
    session: AsyncSession,
    connector_id: uuid.UUID,
    connector_type: str,
    credentials: dict,
    config: dict,
    lookback_days: int = 730,
    progress_callback=None,
) -> dict:
    """
    Pull historical messages from a connector and store them.
    Returns summary statistics.
    """
    adapter_cls = ADAPTER_MAP.get(connector_type)
    if not adapter_cls:
        return {"error": f"No adapter for connector type: {connector_type}", "total_messages": 0}

    adapter = adapter_cls()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=lookback_days)

    total_stored = 0
    batch_num = 0

    async for batch in adapter.pull_history(credentials, config, since, now, progress_callback):
        batch_num += 1
        for msg in batch:
            db_msg = ChannelMessage(
                id=uuid.uuid4(),
                connector_id=connector_id,
                channel=msg.channel,
                author=msg.author,
                content=msg.content,
                message_type="unknown",
                tickers_mentioned=[],
                raw_data=msg.raw_data,
                platform_message_id=msg.platform_message_id,
                posted_at=msg.posted_at,
            )
            session.add(db_msg)
            total_stored += 1

        if batch_num % 5 == 0:
            await session.flush()

    await session.commit()
    logger.info("Ingested %d messages from connector %s", total_stored, connector_id)

    return {
        "total_messages": total_stored,
        "connector_id": str(connector_id),
        "lookback_days": lookback_days,
    }
