"""Backtest request publishing and consumer group management for Redis Streams.

This module provides the messaging layer for the phoenix-backtest-worker pod.
When the API spawns a backtest, it publishes to the Redis stream defined here
instead of running the backtest inline. The worker pod consumes from the stream
and runs the backtest orchestrator out-of-process.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

STREAM_KEY = "backtest:requests"
CONSUMER_GROUP = "backtest-worker"


class BacktestRequest(BaseModel):
    """Backtest request published to Redis stream.

    Fields:
        agent_id: Agent UUID as string.
        backtest_id: AgentBacktest row UUID as string.
        session_id: AgentSession row UUID as string.
        config: Backtest configuration dict (must be JSON-serializable).
        enabled_algorithms: Optional list of algorithm names to enable.
        version: Schema version for forward compatibility (default 1).
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str
    backtest_id: str
    session_id: str
    config: dict[str, Any]
    enabled_algorithms: list[str] | None = None
    version: int = 1


async def publish(redis_client: Any, request: BacktestRequest) -> str:
    """Publish a backtest request to the Redis stream.

    Args:
        redis_client: Redis asyncio client (redis.asyncio.Redis).
        request: BacktestRequest model instance.

    Returns:
        Stream entry ID (e.g., "1234567890-0").

    Raises:
        Any Redis connection errors are propagated to the caller.
    """
    # Serialize config to JSON string so it's safe to store in Redis
    payload = {
        "agent_id": request.agent_id,
        "backtest_id": request.backtest_id,
        "session_id": request.session_id,
        "config": json.dumps(request.config, default=str),
        "enabled_algorithms": json.dumps(request.enabled_algorithms) if request.enabled_algorithms else "",
        "version": str(request.version),
    }
    entry_id = await redis_client.xadd(STREAM_KEY, payload)
    # Redis returns bytes or str depending on decode_responses setting
    return entry_id.decode() if isinstance(entry_id, bytes) else entry_id


async def ensure_consumer_group(redis_client: Any) -> None:
    """Idempotently create the consumer group for backtest workers.

    Args:
        redis_client: Redis asyncio client (redis.asyncio.Redis).

    Raises:
        Any Redis connection errors are propagated to the caller.
    """
    try:
        await redis_client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:
        # BUSYGROUP means the group already exists — safe to ignore
        if "BUSYGROUP" not in str(exc):
            raise
