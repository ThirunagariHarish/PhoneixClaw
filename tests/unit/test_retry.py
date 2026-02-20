import pytest

from shared.retry import RetryExhaustedError, retry_async


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        async def ok():
            return 42

        result = await retry_async(ok, max_retries=3, base_delay=0.01)
        assert result == 42

    @pytest.mark.asyncio
    async def test_succeeds_after_retries(self):
        calls = {"count": 0}

        async def flaky():
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("fail")
            return "ok"

        result = await retry_async(flaky, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert calls["count"] == 3

    @pytest.mark.asyncio
    async def test_exhausted_raises(self):
        async def always_fail():
            raise RuntimeError("always")

        with pytest.raises(RetryExhaustedError):
            await retry_async(always_fail, max_retries=2, base_delay=0.01)

    @pytest.mark.asyncio
    async def test_non_retryable_not_retried(self):
        calls = {"count": 0}

        async def fail():
            calls["count"] += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            await retry_async(
                fail, max_retries=3, base_delay=0.01, retryable_exceptions=(RuntimeError,)
            )
        assert calls["count"] == 1
