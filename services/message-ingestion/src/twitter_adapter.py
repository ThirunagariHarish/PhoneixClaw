"""
Twitter/X message history adapter.
Pulls tweets using the Twitter API v2 search endpoint.
Free tier: 7 days. Academic/Enterprise: full archive.
"""

import logging
from datetime import datetime
from typing import AsyncIterator

import httpx

from .base_adapter import BaseMessageAdapter, RawMessage

logger = logging.getLogger(__name__)

TWITTER_API = "https://api.twitter.com/2"
BATCH_SIZE = 100


class TwitterAdapter(BaseMessageAdapter):

    async def pull_history(
        self,
        credentials: dict,
        config: dict,
        since: datetime,
        until: datetime,
        progress_callback=None,
    ) -> AsyncIterator[list[RawMessage]]:
        bearer = credentials.get("bearer_token", "")
        accounts = config.get("accounts", [])
        keywords = config.get("keywords", [])
        headers = {"Authorization": f"Bearer {bearer}"}

        query_parts = []
        if accounts:
            from_clauses = " OR ".join([f"from:{a}" for a in accounts])
            query_parts.append(f"({from_clauses})")
        if keywords:
            kw_clauses = " OR ".join(keywords)
            query_parts.append(f"({kw_clauses})")

        query = " ".join(query_parts) if query_parts else "stock OR trade OR $SPY"

        total_pulled = 0
        next_token = None

        for _ in range(100):  # Safety limit
            params = {
                "query": query,
                "max_results": min(BATCH_SIZE, 100),
                "tweet.fields": "created_at,author_id,public_metrics,entities",
                "start_time": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_time": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sort_order": "recency",
            }
            if next_token:
                params["next_token"] = next_token

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{TWITTER_API}/tweets/search/recent",
                    headers=headers,
                    params=params,
                )

            if resp.status_code == 429:
                import asyncio
                await asyncio.sleep(15)
                continue

            if resp.status_code != 200:
                logger.warning("Twitter API returned %s", resp.status_code)
                break

            data = resp.json()
            tweets = data.get("data", [])
            if not tweets:
                break

            batch = []
            for tw in tweets:
                posted_at = datetime.fromisoformat(tw["created_at"].replace("Z", "+00:00"))
                batch.append(RawMessage(
                    platform_message_id=tw["id"],
                    channel="twitter",
                    author=tw.get("author_id", "unknown"),
                    content=tw.get("text", ""),
                    posted_at=posted_at,
                    raw_data={
                        "metrics": tw.get("public_metrics", {}),
                        "entities": tw.get("entities", {}),
                    },
                ))

            if batch:
                total_pulled += len(batch)
                if progress_callback:
                    await progress_callback(total_pulled, None)
                yield batch

            meta = data.get("meta", {})
            next_token = meta.get("next_token")
            if not next_token:
                break

    async def test_connection(self, credentials: dict, config: dict) -> tuple[bool, str]:
        bearer = credentials.get("bearer_token", "")
        headers = {"Authorization": f"Bearer {bearer}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{TWITTER_API}/users/me", headers=headers)
        if resp.status_code in (200, 403):
            return True, "Bearer token valid"
        return False, f"Status {resp.status_code}"
