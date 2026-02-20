import logging

import redis.asyncio as redis

from shared.config.base_config import config

logger = logging.getLogger(__name__)


class RedisDedup:
    def __init__(self, prefix: str = "dedup", ttl_seconds: int = 3600):
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._redis = None

    async def connect(self):
        self._redis = redis.from_url(config.redis.url)

    async def close(self):
        if self._redis:
            await self._redis.aclose()

    async def is_duplicate(self, key: str) -> bool:
        if not self._redis:
            return False
        full_key = f"{self._prefix}:{key}"
        result = await self._redis.set(full_key, "1", nx=True, ex=self._ttl)
        return result is None  # None means key already existed

    async def mark_seen(self, key: str) -> None:
        if self._redis:
            await self._redis.set(f"{self._prefix}:{key}", "1", ex=self._ttl)
