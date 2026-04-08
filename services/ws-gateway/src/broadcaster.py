"""
Redis-backed message broadcaster — subscribes to Redis Streams and
forwards messages to WebSocket clients via ChannelManager.

M2.11: Real-time WebSocket gateway.
"""

import asyncio
import logging
import os

import redis.asyncio as redis

from services.ws_gateway.src.channels import ChannelManager

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class RedisBroadcaster:
    """Bridges Redis Streams to WebSocket channels."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        redis_client: redis.Redis | None = None,
    ):
        self._cm = channel_manager
        self._redis = redis_client
        self._stream_map: dict[str, str] = {}
        self._last_ids: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def add_stream(self, stream_name: str, channel_name: str) -> None:
        """Map a Redis stream to a WebSocket channel."""
        self._stream_map[stream_name] = channel_name
        self._last_ids.setdefault(stream_name, "0-0")
        logger.info("Mapped stream %s -> channel %s", stream_name, channel_name)

    async def _ensure_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    async def _poll_loop(self) -> None:
        r = await self._ensure_redis()

        while self._running:
            if not self._stream_map:
                await asyncio.sleep(1)
                continue

            try:
                streams = {name: self._last_ids[name] for name in self._stream_map}
                results = await r.xread(streams, count=100, block=2000)

                for stream_name, entries in results:
                    channel = self._stream_map.get(stream_name)
                    if not channel:
                        continue

                    for entry_id, data in entries:
                        message = {
                            "stream": stream_name,
                            "id": entry_id,
                            "data": data,
                        }
                        await self._cm.broadcast(channel, message)
                        self._last_ids[stream_name] = entry_id

            except redis.ConnectionError:
                logger.warning("Redis connection lost in broadcaster, retrying in 3s")
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Broadcaster poll error")
                await asyncio.sleep(1)

    async def start(self) -> None:
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("RedisBroadcaster started with %d streams", len(self._stream_map))

    async def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        logger.info("RedisBroadcaster stopped")
