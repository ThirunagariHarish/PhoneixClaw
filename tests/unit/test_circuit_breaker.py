import asyncio

import pytest

from shared.broker.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


@pytest.fixture
def cb():
    return CircuitBreaker(failure_threshold=3, recovery_timeout=0.1, half_open_max_calls=1)


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self, cb):
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call(self, cb):
        async def ok():
            return "success"

        result = await cb.call(ok)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self, cb):
        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self, cb):
        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail)
        with pytest.raises(CircuitOpenError):
            await cb.call(fail)

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self, cb):
        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail)
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_recovery(self, cb):
        async def fail():
            raise RuntimeError("boom")

        async def ok():
            return "ok"

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail)
        await asyncio.sleep(0.15)
        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset(self, cb):
        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail)
        cb.reset()
        assert cb.state == CircuitState.CLOSED
