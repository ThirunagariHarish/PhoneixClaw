from __future__ import annotations

import logging
import time

import redis.asyncio as redis

from shared.config.base_config import config

logger = logging.getLogger(__name__)

class SlidingWindowRateLimiter:
    def __init__(self, redis_client: redis.Redis | None = None, max_requests: int = 100, window_seconds: int = 60):
        self._redis = redis_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def connect(self):
        if not self._redis:
            self._redis = redis.from_url(config.redis.url)

    async def close(self):
        if self._redis:
            await self._redis.aclose()

    async def is_allowed(self, key: str) -> bool:
        if not self._redis:
            return True
        now = time.time()
        window_start = now - self.window_seconds
        pipe = self._redis.pipeline()
        full_key = f"ratelimit:{key}"
        pipe.zremrangebyscore(full_key, 0, window_start)
        pipe.zadd(full_key, {str(now): now})
        pipe.zcard(full_key)
        pipe.expire(full_key, self.window_seconds)
        results = await pipe.execute()
        count = results[2]
        allowed = count <= self.max_requests
        if not allowed:
            logger.warning("Rate limit exceeded for %s (%d/%d)", key, count, self.max_requests)
        return allowed
