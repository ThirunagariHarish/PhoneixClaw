"""
Redis Streams event bus client for Phoenix v2.

M2.10: Agent-to-agent communication, event-driven flows.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

import redis.asyncio as redis


class EventBus:
    """Async Redis Streams event bus for publish/subscribe."""

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _client_ensure(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url)
        return self._client

    async def publish(self, stream: str, data: dict[str, Any]) -> str:
        """Publish event to stream. Returns message ID."""
        client = await self._client_ensure()
        msg_id = await client.xadd(stream, data)
        return msg_id

    async def subscribe(
        self, stream: str, group: str, consumer: str
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Subscribe to stream as consumer in group. Yields (msg_id, data)."""
        client = await self._client_ensure()
        try:
            await client.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        while True:
            messages = await client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=10,
                block=5000,
            )
            for _stream_name, stream_messages in messages:
                for raw_id, fields in stream_messages:
                    msg_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
                    data = {
                        (k.decode() if isinstance(k, bytes) else k): (
                            v.decode() if isinstance(v, bytes) else v
                        )
                        for k, v in fields.items()
                    }
                    yield msg_id, data

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """Acknowledge message in consumer group."""
        client = await self._client_ensure()
        await client.xack(stream, group, msg_id)

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
