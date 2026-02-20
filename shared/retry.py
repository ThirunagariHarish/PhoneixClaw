import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class RetryExhaustedError(Exception):
    pass


async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exc = e
            if attempt == max_retries:
                break
            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                "Attempt %d/%d failed (%s), retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)
    raise RetryExhaustedError(f"All {max_retries + 1} attempts failed") from last_exc


def with_retry(max_retries: int = 3, base_delay: float = 1.0, retryable_exceptions: tuple = (Exception,)):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(
                func,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                retryable_exceptions=retryable_exceptions,
                **kwargs,
            )

        return wrapper

    return decorator
