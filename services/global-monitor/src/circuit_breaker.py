"""
Circuit Breaker — kills all active trades if system loses X% in a session
or if AI Confidence Score drops below threshold.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    TRIPPED = "TRIPPED"
    COOLDOWN = "COOLDOWN"


class CircuitBreaker:
    """Hard safety layer for the trading system."""

    def __init__(
        self,
        max_daily_loss_pct: float = 3.0,
        min_confidence: float = 0.3,
        cooldown_minutes: int = 30,
        max_consecutive_losses: int = 5,
        kill_callback: Callable[[], Awaitable[None]] | None = None,
    ):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.min_confidence = min_confidence
        self.cooldown_minutes = cooldown_minutes
        self.max_consecutive_losses = max_consecutive_losses
        self._kill_callback = kill_callback

        self.state = CircuitBreakerState.NORMAL
        self._tripped_at: datetime | None = None
        self._trip_reason: str = ""
        self._warning_threshold_pct = 0.8  # 80% of trip threshold

    def check(
        self,
        daily_pnl_pct: float,
        confidence_score: float,
        consecutive_losses: int,
    ) -> dict[str, Any]:
        """Check all thresholds. Returns state and any kill_switch action needed."""
        result: dict[str, Any] = {
            "state": self.state.value,
            "action": None,
            "reason": None,
        }

        if self.state == CircuitBreakerState.TRIPPED:
            result["action"] = "kill_switch"
            result["reason"] = self._trip_reason
            return result

        if self.state == CircuitBreakerState.COOLDOWN:
            if self._cooldown_elapsed():
                self._transition(CircuitBreakerState.NORMAL, "Cooldown elapsed")
            return result

        # Check trip conditions
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            asyncio.create_task(self.trip(f"Daily loss {daily_pnl_pct:.2f}% exceeds -{self.max_daily_loss_pct}%"))
            result["action"] = "kill_switch"
            result["reason"] = f"Daily loss threshold breached: {daily_pnl_pct:.2f}%"
            return result

        if confidence_score < self.min_confidence:
            asyncio.create_task(self.trip(f"AI confidence {confidence_score:.2f} below {self.min_confidence}"))
            result["action"] = "kill_switch"
            result["reason"] = f"Confidence below threshold: {confidence_score:.2f}"
            return result

        if consecutive_losses >= self.max_consecutive_losses:
            asyncio.create_task(self.trip(f"Consecutive losses: {consecutive_losses}"))
            result["action"] = "kill_switch"
            result["reason"] = f"Max consecutive losses: {consecutive_losses}"
            return result

        # Check warning conditions (80% of trip threshold)
        warning_loss = -self.max_daily_loss_pct * self._warning_threshold_pct
        if daily_pnl_pct <= warning_loss and self.state == CircuitBreakerState.NORMAL:
            self._transition(CircuitBreakerState.WARNING, f"Approaching loss limit: {daily_pnl_pct:.2f}%")
        elif confidence_score < self.min_confidence * 1.2 and self.state == CircuitBreakerState.NORMAL:
            self._transition(CircuitBreakerState.WARNING, f"Confidence declining: {confidence_score:.2f}")
        elif consecutive_losses >= int(self.max_consecutive_losses * self._warning_threshold_pct):
            if self.state == CircuitBreakerState.NORMAL:
                self._transition(CircuitBreakerState.WARNING, f"Consecutive losses: {consecutive_losses}")

        result["state"] = self.state.value
        return result

    def _transition(self, new_state: CircuitBreakerState, reason: str) -> None:
        old = self.state
        self.state = new_state
        logger.info("CircuitBreaker %s -> %s: %s", old.value, new_state.value, reason)

    def _cooldown_elapsed(self) -> bool:
        if not self._tripped_at:
            return True
        elapsed = datetime.now(timezone.utc) - self._tripped_at
        return elapsed >= timedelta(minutes=self.cooldown_minutes)

    async def trip(self, reason: str) -> None:
        """Trip the circuit breaker - kill all active trades."""
        self._transition(CircuitBreakerState.TRIPPED, reason)
        self._tripped_at = datetime.now(timezone.utc)
        self._trip_reason = reason
        logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)
        await self.kill_all_positions()
        self._transition(CircuitBreakerState.COOLDOWN, "Entering cooldown after trip")

    async def kill_all_positions(self) -> None:
        """Emergency: close all open positions across all agents."""
        logger.warning("CircuitBreaker: kill_all_positions invoked")
        if self._kill_callback:
            await self._kill_callback()
        # In production, this would call broker APIs to close positions

    def reset(self) -> None:
        """Manual reset after cooldown."""
        self.state = CircuitBreakerState.NORMAL
        self._tripped_at = None
        self._trip_reason = ""
        logger.info("CircuitBreaker manually reset to NORMAL")

    def get_status(self) -> dict[str, Any]:
        """Return full state for monitoring."""
        return {
            "state": self.state.value,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "min_confidence": self.min_confidence,
            "max_consecutive_losses": self.max_consecutive_losses,
            "cooldown_minutes": self.cooldown_minutes,
            "tripped_at": self._tripped_at.isoformat() if self._tripped_at else None,
            "trip_reason": self._trip_reason,
            "cooldown_elapsed": self._cooldown_elapsed() if self.state == CircuitBreakerState.COOLDOWN else None,
        }
