import asyncio

import pytest

from shared.graceful_shutdown import GracefulShutdown


class TestGracefulShutdown:
    def test_initially_not_shutting_down(self):
        gs = GracefulShutdown()
        assert gs.is_shutting_down is False

    @pytest.mark.asyncio
    async def test_cleanup_handlers_called(self):
        gs = GracefulShutdown()
        called = []

        async def cleanup1():
            called.append("c1")

        async def cleanup2():
            called.append("c2")

        gs.register(cleanup1)
        gs.register(cleanup2)
        await gs.run_cleanup()
        assert "c1" in called
        assert "c2" in called

    @pytest.mark.asyncio
    async def test_cleanup_timeout(self):
        gs = GracefulShutdown()

        async def slow():
            await asyncio.sleep(10)

        gs.register(slow)
        await gs.run_cleanup(timeout=0.1)  # should not hang
