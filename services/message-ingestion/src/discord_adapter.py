"""
Discord message history adapter.
Pulls channel messages using the Discord REST API with pagination.
"""

import logging
from datetime import datetime
from typing import AsyncIterator

import httpx

from .base_adapter import BaseMessageAdapter, RawMessage

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
BATCH_SIZE = 100


class DiscordAdapter(BaseMessageAdapter):

    async def pull_history(
        self,
        credentials: dict,
        config: dict,
        since: datetime,
        until: datetime,
        progress_callback=None,
    ) -> AsyncIterator[list[RawMessage]]:
        token = credentials.get("user_token") or credentials.get("bot_token", "")
        channels = config.get("selected_channels", [])
        auth_type = config.get("auth_type", "user_token")
        headers = {"Authorization": f"Bot {token}" if auth_type == "bot" else token}

        total_pulled = 0

        for ch_info in channels:
            channel_id = ch_info.get("channel_id") or ch_info
            channel_name = ch_info.get("channel_name", str(channel_id))
            before_id = None

            while True:
                params = {"limit": BATCH_SIZE}
                if before_id:
                    params["before"] = before_id

                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        f"{DISCORD_API}/channels/{channel_id}/messages",
                        headers=headers,
                        params=params,
                    )

                if resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", 1)
                    import asyncio
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code != 200:
                    logger.warning("Discord API returned %s for channel %s", resp.status_code, channel_id)
                    break

                messages = resp.json()
                if not messages:
                    break

                batch = []
                stop = False
                for msg in messages:
                    posted_at = datetime.fromisoformat(msg["timestamp"].replace("+00:00", "+00:00"))
                    if posted_at < since:
                        stop = True
                        break
                    if posted_at > until:
                        continue
                    batch.append(RawMessage(
                        platform_message_id=msg["id"],
                        channel=channel_name,
                        author=msg.get("author", {}).get("username", "unknown"),
                        content=msg.get("content", ""),
                        posted_at=posted_at,
                        raw_data={
                            "embeds": msg.get("embeds", []),
                            "attachments": msg.get("attachments", []),
                            "author_id": msg.get("author", {}).get("id"),
                        },
                    ))

                if batch:
                    total_pulled += len(batch)
                    if progress_callback:
                        await progress_callback(total_pulled, None)
                    yield batch

                if stop or len(messages) < BATCH_SIZE:
                    break

                before_id = messages[-1]["id"]

    async def test_connection(self, credentials: dict, config: dict) -> tuple[bool, str]:
        token = credentials.get("user_token") or credentials.get("bot_token", "")
        auth_type = config.get("auth_type", "user_token")
        headers = {"Authorization": f"Bot {token}" if auth_type == "bot" else token}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{DISCORD_API}/users/@me", headers=headers)
        if resp.status_code == 200:
            return True, resp.json().get("username", "OK")
        return False, f"Status {resp.status_code}"
