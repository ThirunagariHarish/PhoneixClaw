"""Tests for worker_manager module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.pipeline_worker.src.worker_manager import WorkerManager


def _mock_session_factory():
    """Create a mock async context manager session factory."""
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            pass

    return _SessionCtx


class TestWorkerManager:
    def test_initial_state(self):
        redis = AsyncMock()
        mgr = WorkerManager(redis, _mock_session_factory())
        assert mgr.active_count == 0
        assert mgr.list_workers() == []

    @pytest.mark.asyncio
    async def test_start_worker(self):
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])

        mgr = WorkerManager(redis, _mock_session_factory())

        with patch.object(mgr, "_record_session_start", new_callable=AsyncMock):
            result = await mgr.start_worker("agent-1", ["conn-1"], {"risk_params": {}})

        assert result["agent_id"] == "agent-1"
        assert result["status"] == "starting"
        assert "stream:channel:conn-1" in result["stream_keys"]
        assert mgr.active_count == 1

        # Cleanup
        for task in mgr._workers.values():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_start_duplicate_worker(self):
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])

        mgr = WorkerManager(redis, _mock_session_factory())

        with patch.object(mgr, "_record_session_start", new_callable=AsyncMock):
            await mgr.start_worker("agent-1", ["conn-1"], {})
            result = await mgr.start_worker("agent-1", ["conn-1"], {})

        assert result["status"] == "already_running"

        for task in mgr._workers.values():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_stop_nonexistent_worker(self):
        redis = AsyncMock()
        mgr = WorkerManager(redis, _mock_session_factory())
        assert await mgr.stop_worker("nonexistent") is False

    @pytest.mark.asyncio
    async def test_get_worker_none(self):
        redis = AsyncMock()
        mgr = WorkerManager(redis, _mock_session_factory())
        assert mgr.get_worker("nonexistent") is None

    @pytest.mark.asyncio
    async def test_recover_with_no_agents(self):
        redis = AsyncMock()
        mgr = WorkerManager(redis, _mock_session_factory())
        recovered = await mgr.recover_workers()
        assert recovered == 0
