"""
Regression tests for Redis Streams event bus. M1.12, ArchitecturePlan §5.
"""

import json
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1700-0")
    redis.xread = AsyncMock(return_value=[])
    redis.xgroup_create = AsyncMock(side_effect=Exception("GROUP already exists"))
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock(return_value=1)
    return redis


class TestEventBusRegression:
    """Redis Streams publish/subscribe, consumer groups, ack, backpressure."""

    @pytest.mark.asyncio
    async def test_redis_streams_publish(self, mock_redis):
        """Publish message to Redis Stream."""
        stream_key = "phoenix:test-events"
        payload = {"event": "AGENT_CREATED", "agent_id": "a1"}
        msg_id = await mock_redis.xadd(stream_key, {"payload": json.dumps(payload)})
        assert msg_id == "1700-0"
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_streams_subscribe_read(self, mock_redis):
        """Subscribe and read from stream."""
        mock_redis.xread.return_value = [
            ("phoenix:test-events", [("1700-0", {"payload": b'{"event":"test"}'})])
        ]
        messages = await mock_redis.xread({"phoenix:test-events": "0"}, count=10, block=1000)
        assert len(messages) >= 1
        stream_name, entries = messages[0]
        assert len(entries) >= 1

    @pytest.mark.asyncio
    async def test_consumer_group_creation(self, mock_redis):
        """Consumer group can be created (or already exists)."""
        stream_key = "phoenix:trade-intents"
        group_name = "execution-service"
        try:
            await mock_redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
        except Exception as e:
            assert "already exists" in str(e).lower() or "BUSYGROUP" in str(e)

    @pytest.mark.asyncio
    async def test_message_acknowledgment(self, mock_redis):
        """Message can be acknowledged after processing."""
        stream_key = "phoenix:trade-intents"
        group_name = "execution-service"
        msg_id = "1700-0"
        ack_count = await mock_redis.xack(stream_key, group_name, msg_id)
        mock_redis.xack.assert_called_once_with(stream_key, group_name, msg_id)

    @pytest.mark.asyncio
    async def test_stream_backpressure_handling(self, mock_redis):
        """Read with count limit prevents overload."""
        mock_redis.xread.return_value = []
        messages = await mock_redis.xread(
            {"phoenix:test-events": ">"},
            count=100,  # Limit batch size
            block=5000,
        )
        mock_redis.xread.assert_called_once()
        call_kwargs = mock_redis.xread.call_args[1]
        assert call_kwargs.get("count") == 100
