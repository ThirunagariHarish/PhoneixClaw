"""
Async retry decorator for Phoenix v2.
"""

import asyncio
import functools
import sys
from collections.abc import Awaitable, Callable

if sys.version_info >= (3, 10):
    from typing import ParamSpec, TypeVar
else:
    from typing import TypeVar

    from typing_extensions import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")


def async_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
):
    """Decorator that retries an async function with exponential backoff."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exc = None
            d = delay
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt == max_retries:
                        raise
                    await asyncio.sleep(d)
                    d *= backoff
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
