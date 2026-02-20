from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.rate_limiter import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter:
    @pytest.mark.asyncio
    async def test_allowed_when_no_redis(self):
        limiter = SlidingWindowRateLimiter(redis_client=None)
        assert await limiter.is_allowed("test-key") is True

    @pytest.mark.asyncio
    async def test_allowed_under_limit(self):
        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[None, None, 5, None])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        limiter = SlidingWindowRateLimiter(redis_client=mock_redis, max_requests=100)
        assert await limiter.is_allowed("user:123") is True

    @pytest.mark.asyncio
    async def test_blocked_over_limit(self):
        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[None, None, 101, None])
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        limiter = SlidingWindowRateLimiter(redis_client=mock_redis, max_requests=100)
        assert await limiter.is_allowed("user:123") is False
