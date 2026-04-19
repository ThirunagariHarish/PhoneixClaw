"""Tests for publisher module."""

from unittest.mock import AsyncMock

import pytest

from services.pipeline_worker.src.pipeline.publisher import (
    log_to_api,
    publish_decision,
    publish_trade_intent,
    publish_watchlist,
)


class TestPublishTradeIntent:
    @pytest.mark.asyncio
    async def test_publishes_to_stream(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1234-0")

        intent = {"agent_id": "a1", "symbol": "AAPL", "side": "buy", "qty": 1}
        msg_id = await publish_trade_intent(redis, intent)

        assert msg_id == "1234-0"
        redis.xadd.assert_called_once()
        call_args = redis.xadd.call_args
        assert call_args[0][0] == "stream:trade-intents"

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(side_effect=Exception("connection lost"))

        result = await publish_trade_intent(redis, {"agent_id": "a1"})
        assert result is None


class TestPublishWatchlist:
    @pytest.mark.asyncio
    async def test_posts_to_broker(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        http = AsyncMock()
        http.post = AsyncMock(return_value=mock_response)

        ok = await publish_watchlist(http, "http://broker:8030", "AAPL", "agent-1")
        assert ok is True

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self):
        http = AsyncMock()
        http.post = AsyncMock(side_effect=Exception("timeout"))

        ok = await publish_watchlist(http, "http://broker:8030", "AAPL", "agent-1")
        assert ok is False


class TestPublishDecision:
    @pytest.mark.asyncio
    async def test_publishes_to_agent_messages(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="5678-0")

        decision = {"action": "EXECUTE", "ticker": "AAPL", "final_confidence": 0.85, "reasons": []}
        msg_id = await publish_decision(redis, "agent-1", decision)
        assert msg_id == "5678-0"


class TestLogToApi:
    @pytest.mark.asyncio
    async def test_posts_log(self):
        mock_response = AsyncMock()
        mock_response.status_code = 201
        http = AsyncMock()
        http.post = AsyncMock(return_value=mock_response)

        ok = await log_to_api(http, "http://api:8011", "agent-1", {"level": "INFO", "message": "test"})
        assert ok is True
        http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        http = AsyncMock()
        http.post = AsyncMock(side_effect=Exception("timeout"))

        ok = await log_to_api(http, "http://api:8011", "agent-1", {"level": "INFO", "message": "test"})
        assert ok is False
