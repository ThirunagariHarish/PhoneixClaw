import logging
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit breaker transitioning to HALF_OPEN")
        return self._state

    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        current_state = self.state
        if current_state == CircuitState.OPEN:
            raise CircuitOpenError("Circuit breaker is OPEN")

        if current_state == CircuitState.HALF_OPEN and self._half_open_calls >= self.half_open_max_calls:
            raise CircuitOpenError("Circuit breaker HALF_OPEN limit reached")

        try:
            if current_state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self):
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker recovered, transitioning to CLOSED")
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN after %d failures", self._failure_count)

    def reset(self):
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0


class CircuitOpenError(Exception):
    pass
