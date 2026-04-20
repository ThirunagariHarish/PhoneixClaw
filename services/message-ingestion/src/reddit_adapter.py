"""
Reddit message history adapter.
Pulls subreddit posts using the Reddit JSON API with pagination.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from .base_adapter import BaseMessageAdapter, RawMessage

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


class RedditAdapter(BaseMessageAdapter):

    async def _get_access_token(self, credentials: dict) -> str | None:
        client_id = credentials.get("client_id", "")
        client_secret = credentials.get("client_secret", "")
        user_agent = credentials.get("user_agent", "PhoenixTrade/1.0")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"User-Agent": user_agent},
            )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        return None

    async def pull_history(
        self,
        credentials: dict,
        config: dict,
        since: datetime,
        until: datetime,
        progress_callback=None,
    ) -> AsyncIterator[list[RawMessage]]:
        token = await self._get_access_token(credentials)
        if not token:
            logger.error("Failed to get Reddit access token")
            return

        user_agent = credentials.get("user_agent", "PhoenixTrade/1.0")
        subreddits = config.get("subreddits", [])
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
        }

        total_pulled = 0

        for sub in subreddits:
            after = None
            for _ in range(50):  # Safety limit: 50 pages per subreddit
                params = {"limit": BATCH_SIZE, "sort": "new", "t": "all"}
                if after:
                    params["after"] = after

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"https://oauth.reddit.com/r/{sub}/new",
                        headers=headers,
                        params=params,
                    )

                if resp.status_code != 200:
                    logger.warning("Reddit API returned %s for r/%s", resp.status_code, sub)
                    break

                data = resp.json().get("data", {})
                children = data.get("children", [])
                if not children:
                    break

                batch = []
                stop = False
                for child in children:
                    post = child.get("data", {})
                    created_utc = post.get("created_utc", 0)
                    posted_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

                    if posted_at < since:
                        stop = True
                        break
                    if posted_at > until:
                        continue

                    content = post.get("title", "")
                    selftext = post.get("selftext", "")
                    if selftext:
                        content = f"{content}\n\n{selftext}"

                    batch.append(RawMessage(
                        platform_message_id=post.get("id", ""),
                        channel=f"r/{sub}",
                        author=post.get("author", "unknown"),
                        content=content,
                        posted_at=posted_at,
                        raw_data={
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "url": post.get("url", ""),
                            "flair": post.get("link_flair_text"),
                            "upvote_ratio": post.get("upvote_ratio", 0),
                        },
                    ))

                if batch:
                    total_pulled += len(batch)
                    if progress_callback:
                        await progress_callback(total_pulled, None)
                    yield batch

                after = data.get("after")
                if stop or not after:
                    break

    async def test_connection(self, credentials: dict, config: dict) -> tuple[bool, str]:
        token = await self._get_access_token(credentials)
        if token:
            return True, "Reddit OAuth credentials valid"
        return False, "Could not obtain access token"
