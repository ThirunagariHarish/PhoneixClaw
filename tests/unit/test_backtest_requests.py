"""Unit tests for shared.messaging.backtest_requests module."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from shared.messaging.backtest_requests import (
    CONSUMER_GROUP,
    STREAM_KEY,
    BacktestRequest,
    ensure_consumer_group,
    publish,
)


class TestBacktestRequest:
    """Test BacktestRequest model."""

    def test_minimal_request(self):
        """Test creating a minimal BacktestRequest."""
        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={"foo": "bar"},
        )
        assert req.agent_id == "agent-123"
        assert req.backtest_id == "bt-456"
        assert req.session_id == "sess-789"
        assert req.config == {"foo": "bar"}
        assert req.enabled_algorithms is None
        assert req.version == 1

    def test_full_request(self):
        """Test creating a BacktestRequest with all fields."""
        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={"symbols": ["AAPL", "MSFT"], "timeframe": "1d"},
            enabled_algorithms=["xgboost", "lightgbm"],
            version=2,
        )
        assert req.agent_id == "agent-123"
        assert req.enabled_algorithms == ["xgboost", "lightgbm"]
        assert req.version == 2

    def test_immutable(self):
        """Test that BacktestRequest is frozen (immutable)."""
        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={},
        )
        with pytest.raises(Exception):  # pydantic validation error on frozen model
            req.agent_id = "different"

    def test_json_serializable_config(self):
        """Test that config accepts various JSON-serializable types."""
        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={
                "start_date": "2024-01-01",  # already a string (recommended)
                "symbols": ["AAPL"],
                "nested": {"key": 123},
            },
        )
        # Should serialize without error
        json.dumps(req.config, default=str)


class TestPublish:
    """Test publish function."""

    @pytest.mark.asyncio
    async def test_publish_success(self):
        """Test successful publish to Redis stream."""
        redis_mock = AsyncMock()
        redis_mock.xadd.return_value = b"1234567890-0"

        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={"foo": "bar"},
            enabled_algorithms=["xgboost"],
        )

        entry_id = await publish(redis_mock, req)

        assert entry_id == "1234567890-0"
        redis_mock.xadd.assert_called_once()
        call_args = redis_mock.xadd.call_args
        assert call_args[0][0] == STREAM_KEY
        payload = call_args[0][1]
        assert payload["agent_id"] == "agent-123"
        assert payload["backtest_id"] == "bt-456"
        assert payload["session_id"] == "sess-789"
        assert json.loads(payload["config"]) == {"foo": "bar"}
        assert json.loads(payload["enabled_algorithms"]) == ["xgboost"]
        assert payload["version"] == "1"

    @pytest.mark.asyncio
    async def test_publish_no_algorithms(self):
        """Test publish when enabled_algorithms is None."""
        redis_mock = AsyncMock()
        redis_mock.xadd.return_value = "1234567890-0"

        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={},
        )

        await publish(redis_mock, req)

        call_args = redis_mock.xadd.call_args
        payload = call_args[0][1]
        assert payload["enabled_algorithms"] == ""

    @pytest.mark.asyncio
    async def test_publish_str_entry_id(self):
        """Test publish when Redis returns string entry ID (decode_responses=True)."""
        redis_mock = AsyncMock()
        redis_mock.xadd.return_value = "1234567890-0"  # already decoded

        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={},
        )

        entry_id = await publish(redis_mock, req)
        assert entry_id == "1234567890-0"

    @pytest.mark.asyncio
    async def test_publish_propagates_redis_error(self):
        """Test that Redis connection errors are propagated."""
        redis_mock = AsyncMock()
        redis_mock.xadd.side_effect = ConnectionError("Redis unavailable")

        req = BacktestRequest(
            agent_id="agent-123",
            backtest_id="bt-456",
            session_id="sess-789",
            config={},
        )

        with pytest.raises(ConnectionError, match="Redis unavailable"):
            await publish(redis_mock, req)


class TestEnsureConsumerGroup:
    """Test ensure_consumer_group function."""

    @pytest.mark.asyncio
    async def test_create_group_success(self):
        """Test successful consumer group creation."""
        redis_mock = AsyncMock()
        redis_mock.xgroup_create.return_value = True

        await ensure_consumer_group(redis_mock)

        redis_mock.xgroup_create.assert_called_once_with(
            STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
        )

    @pytest.mark.asyncio
    async def test_create_group_already_exists(self):
        """Test idempotency when consumer group already exists (BUSYGROUP)."""
        redis_mock = AsyncMock()
        redis_mock.xgroup_create.side_effect = Exception("BUSYGROUP Consumer Group name already exists")

        # Should not raise
        await ensure_consumer_group(redis_mock)

    @pytest.mark.asyncio
    async def test_create_group_propagates_non_busygroup_error(self):
        """Test that non-BUSYGROUP errors are propagated."""
        redis_mock = AsyncMock()
        redis_mock.xgroup_create.side_effect = ConnectionError("Redis unavailable")

        with pytest.raises(ConnectionError, match="Redis unavailable"):
            await ensure_consumer_group(redis_mock)

    @pytest.mark.asyncio
    async def test_create_group_other_redis_error(self):
        """Test that other Redis errors are propagated."""
        redis_mock = AsyncMock()
        redis_mock.xgroup_create.side_effect = Exception("ERR wrong number of arguments")

        with pytest.raises(Exception, match="wrong number of arguments"):
            await ensure_consumer_group(redis_mock)
