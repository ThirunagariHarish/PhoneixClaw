"""
Deduplication helper using Redis for Phoenix v2.
"""


import redis.asyncio as redis


class Deduplicator:
    """Redis-based deduplication to avoid processing the same key twice within TTL."""

    def __init__(self, redis_url: str, prefix: str = "dedup"):
        self._redis_url = redis_url
        self._prefix = prefix
        self._client: redis.Redis | None = None

    async def _client_ensure(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url)
        return self._client

    async def is_duplicate(self, key: str, ttl: int = 3600) -> bool:
        """True if key was already seen (duplicate)."""
        client = await self._client_ensure()
        full_key = f"{self._prefix}:{key}"
        result = await client.set(full_key, "1", nx=True, ex=ttl)
        return result is None

    async def mark_processed(self, key: str, ttl: int = 3600) -> None:
        """Mark key as processed (seen)."""
        client = await self._client_ensure()
        await client.set(f"{self._prefix}:{key}", "1", ex=ttl)
