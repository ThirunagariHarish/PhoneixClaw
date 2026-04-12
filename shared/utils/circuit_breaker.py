"""Three-state circuit breaker for external service calls.

States:
  CLOSED  → Normal operation. Calls pass through.
  OPEN    → Service is down. Calls fail-fast without hitting the service.
  HALF_OPEN → After cooldown, allow one probe call. If it succeeds → CLOSED.
              If it fails → back to OPEN.

Usage:
    breaker = CircuitBreaker("robinhood", failure_threshold=3, cooldown_seconds=300)

    async with breaker:
        result = await call_robinhood_api()

    # Or check explicitly:
    if breaker.is_open:
        return {"error": "Robinhood API circuit breaker open"}
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open."""

    def __init__(self, name: str, failures: int, cooldown_remaining: float):
        self.name = name
        self.failures = failures
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker '{name}' is OPEN after {failures} failures. "
            f"Cooldown: {cooldown_remaining:.0f}s remaining."
        )


class CircuitBreaker:
    """Coroutine-safe circuit breaker with three states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 300,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

        self._total_failures = 0
        self._total_successes = 0
        self._total_rejections = 0

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.cooldown_seconds:
                return self.HALF_OPEN
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == self.CLOSED

    def status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self._failure_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "total_rejections": self._total_rejections,
            "cooldown_remaining": max(
                0, self.cooldown_seconds - (time.monotonic() - self._last_failure_time)
            ) if self._state == self.OPEN else 0,
        }

    async def __aenter__(self):
        async with self._lock:
            current_state = self.state

            if current_state == self.OPEN:
                self._total_rejections += 1
                remaining = self.cooldown_seconds - (time.monotonic() - self._last_failure_time)
                raise CircuitBreakerOpen(self.name, self._failure_count, remaining)

            if current_state == self.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self._total_rejections += 1
                    raise CircuitBreakerOpen(self.name, self._failure_count, 0)
                self._half_open_calls += 1

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self._lock:
            if exc_type is None:
                self._on_success()
            else:
                self._on_failure()
        return False  # Don't suppress the exception

    def _on_success(self) -> None:
        self._total_successes += 1
        if self._state in (self.HALF_OPEN, self.OPEN):
            logger.info("Circuit breaker '%s': CLOSED (probe succeeded)", self.name)
        self._state = self.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            self._half_open_calls = 0
            logger.warning(
                "Circuit breaker '%s': OPEN (half-open probe failed, cooldown=%.0fs)",
                self.name, self.cooldown_seconds,
            )
        elif self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            logger.warning(
                "Circuit breaker '%s': OPEN after %d consecutive failures (cooldown=%.0fs)",
                self.name, self._failure_count, self.cooldown_seconds,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = self.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        logger.info("Circuit breaker '%s': manually reset to CLOSED", self.name)


# Singleton breakers for common services
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    cooldown_seconds: float = 300,
) -> CircuitBreaker:
    """Get or create a named circuit breaker singleton."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    return _breakers[name]
