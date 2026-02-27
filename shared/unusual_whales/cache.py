"""
Simple in-memory TTL cache for Unusual Whales API responses.
Falls back to in-memory if Redis is unavailable.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TTL = 300  # 5 minutes


@dataclass
class CacheEntry:
    value: str
    expires_at: float


class InMemoryCache:
    """Thread-safe in-memory cache with TTL expiry."""

    def __init__(self):
        self._store: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    async def set(self, key: str, value: str, ttl: int = DEFAULT_TTL):
        async with self._lock:
            self._store[key] = CacheEntry(
                value=value,
                expires_at=time.time() + ttl,
            )

    async def delete(self, key: str):
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self):
        async with self._lock:
            self._store.clear()

    async def cleanup_expired(self):
        async with self._lock:
            now = time.time()
            expired = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired:
                del self._store[k]


class UWCache:
    """Cache layer for Unusual Whales data. Uses Redis if available, else in-memory."""

    def __init__(self, redis_url: str | None = None, default_ttl: int = DEFAULT_TTL):
        self.default_ttl = default_ttl
        self._redis = None
        self._memory = InMemoryCache()
        self._redis_url = redis_url

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url)
            await self._redis.ping()
            logger.info("UWCache connected to Redis")
            return self._redis
        except Exception as e:
            logger.warning("Redis unavailable, using in-memory cache: %s", e)
            self._redis = None
            return None

    async def get(self, key: str) -> dict | None:
        prefixed = f"uw:{key}"
        r = await self._get_redis()
        if r:
            try:
                val = await r.get(prefixed)
                if val:
                    return json.loads(val)
            except Exception:
                pass

        val = await self._memory.get(prefixed)
        if val:
            return json.loads(val)
        return None

    async def set(self, key: str, data: dict, ttl: int | None = None):
        prefixed = f"uw:{key}"
        ttl = ttl or self.default_ttl
        serialized = json.dumps(data, default=str)

        r = await self._get_redis()
        if r:
            try:
                await r.setex(prefixed, ttl, serialized)
                return
            except Exception:
                pass

        await self._memory.set(prefixed, serialized, ttl)

    async def invalidate(self, key: str):
        prefixed = f"uw:{key}"
        r = await self._get_redis()
        if r:
            try:
                await r.delete(prefixed)
            except Exception:
                pass
        await self._memory.delete(prefixed)
