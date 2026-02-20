from unittest.mock import AsyncMock

import pytest

from shared.dedup import RedisDedup


class TestRedisDedup:
    @pytest.mark.asyncio
    async def test_first_message_not_duplicate(self):
        dedup = RedisDedup()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX succeeded
        dedup._redis = mock_redis
        assert await dedup.is_duplicate("msg-1") is False

    @pytest.mark.asyncio
    async def test_second_message_is_duplicate(self):
        dedup = RedisDedup()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # NX failed (key exists)
        dedup._redis = mock_redis
        assert await dedup.is_duplicate("msg-1") is True

    @pytest.mark.asyncio
    async def test_no_redis_returns_false(self):
        dedup = RedisDedup()
        assert await dedup.is_duplicate("any") is False
