"""
Redis stream publisher for Polymarket news collectors.

The publisher writes each :class:`PMNewsItem` to the ``pm:news`` Redis
stream (configurable). The stream key is intentionally distinct from
any existing twitter/reddit/discord topics so this pipeline is fully
isolated, per Phase 14 DoD.

The future F6 news reactor (v1.2) will consume this stream via a
consumer group; v1.0 only writes.
"""

from __future__ import annotations

import logging
from typing import Protocol

from .base import PMNewsItem

logger = logging.getLogger(__name__)

DEFAULT_STREAM = "pm:news"
DEFAULT_MAXLEN = 50_000


class RedisLike(Protocol):
    async def xadd(
        self,
        name: str,
        fields: dict,
        *,
        maxlen: int | None = ...,
        approximate: bool = ...,
    ) -> str: ...


class PMNewsPublisher:
    """Publishes PM news items to a Redis stream."""

    def __init__(
        self,
        redis: RedisLike,
        *,
        stream: str = DEFAULT_STREAM,
        maxlen: int = DEFAULT_MAXLEN,
    ) -> None:
        self._redis = redis
        self._stream = stream
        self._maxlen = maxlen
        self.published_count = 0

    @property
    def stream(self) -> str:
        return self._stream

    async def publish(self, item: PMNewsItem) -> str | None:
        fields = item.to_stream_fields()
        try:
            entry_id = await self._redis.xadd(
                self._stream,
                fields,
                maxlen=self._maxlen,
                approximate=True,
            )
        except Exception as exc:
            logger.warning("PMNewsPublisher xadd failed: %s", exc)
            return None
        self.published_count += 1
        return entry_id
