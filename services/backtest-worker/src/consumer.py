"""Redis stream consumer abstraction for backtest-worker.

Connects to Redis, creates consumer group if missing, blocks on XREADGROUP,
and handles PEL (pending entries list) for abandoned messages on startup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any, AsyncGenerator

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisStreamConsumer:
    """Redis stream consumer with automatic PEL recovery."""

    def __init__(
        self,
        redis_url: str,
        stream_key: str,
        group_name: str,
        consumer_name: str | None = None,
        block_ms: int = 5000,
        claim_min_idle_time_ms: int = 60000,
    ):
        self.redis_url = redis_url
        self.stream_key = stream_key
        self.group_name = group_name
        self.consumer_name = consumer_name or socket.gethostname()
        self.block_ms = block_ms
        self.claim_min_idle_time_ms = claim_min_idle_time_ms
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis and ensure consumer group exists."""
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        try:
            await self.client.ping()
            logger.info("Connected to Redis at %s", self.redis_url)
        except Exception as e:
            logger.error("Failed to connect to Redis: %s", e)
            raise

        # Create consumer group if missing
        try:
            await self.client.xgroup_create(
                self.stream_key, self.group_name, id="0", mkstream=True
            )
            logger.info(
                "Created consumer group '%s' on stream '%s'",
                self.group_name, self.stream_key,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(
                    "Consumer group '%s' already exists on stream '%s'",
                    self.group_name, self.stream_key,
                )
            else:
                raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.aclose()

    async def claim_abandoned_messages(self) -> list[tuple[str, dict[str, Any]]]:
        """Claim abandoned messages from PEL on startup.

        Returns list of (message_id, payload) tuples.
        """
        if not self.client:
            return []

        try:
            # Read pending entries for all consumers (start="-", end="+")
            pending = await self.client.xpending_range(
                self.stream_key,
                self.group_name,
                min="-",
                max="+",
                count=100,
            )

            claimed_messages = []
            for entry in pending:
                msg_id = entry["message_id"]
                idle_time = entry["time_since_delivered"]

                # Only claim if idle > threshold
                if idle_time >= self.claim_min_idle_time_ms:
                    # Claim the message
                    claimed = await self.client.xclaim(
                        self.stream_key,
                        self.group_name,
                        self.consumer_name,
                        min_idle_time=self.claim_min_idle_time_ms,
                        message_ids=[msg_id],
                    )

                    for claimed_msg in claimed:
                        payload = claimed_msg[1]
                        claimed_messages.append((msg_id, payload))
                        logger.info(
                            "Claimed abandoned message %s (idle %dms)",
                            msg_id, idle_time,
                        )

            return claimed_messages

        except Exception as e:
            logger.warning("Failed to claim abandoned messages: %s", e)
            return []

    async def consume(self) -> AsyncGenerator[tuple[str, dict[str, Any]], None]:
        """Consume messages from Redis stream.

        Yields (message_id, payload) tuples.
        """
        if not self.client:
            raise RuntimeError("Consumer not connected — call connect() first")

        # First, claim any abandoned messages
        abandoned = await self.claim_abandoned_messages()
        for msg_id, payload in abandoned:
            yield msg_id, payload

        # Then enter main consume loop
        logger.info(
            "Starting consume loop: stream=%s group=%s consumer=%s",
            self.stream_key, self.group_name, self.consumer_name,
        )

        while True:
            try:
                # XREADGROUP BLOCK with ">" to read only new messages
                messages = await self.client.xreadgroup(
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams={self.stream_key: ">"},
                    count=1,
                    block=self.block_ms,
                )

                if not messages:
                    # Timeout, loop again
                    await asyncio.sleep(0.1)
                    continue

                # messages is [[stream_key, [(msg_id, payload), ...]]]
                for stream_name, stream_messages in messages:
                    for msg_id, payload in stream_messages:
                        yield msg_id, payload

            except asyncio.CancelledError:
                logger.info("Consumer cancelled, exiting")
                break
            except Exception as e:
                logger.error("Error in consume loop: %s", e)
                await asyncio.sleep(5)

    async def ack(self, message_id: str) -> None:
        """Acknowledge a message."""
        if self.client:
            await self.client.xack(self.stream_key, self.group_name, message_id)


def get_consumer() -> RedisStreamConsumer:
    """Factory to create a configured consumer."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    consumer_name = socket.gethostname()
    return RedisStreamConsumer(
        redis_url=redis_url,
        stream_key="backtest:requests",
        group_name="backtest-worker",
        consumer_name=consumer_name,
        block_ms=5000,
        claim_min_idle_time_ms=60000,  # 1 minute
    )
