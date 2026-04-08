from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from services.global_monitor.src.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
)


class TestCircuitBreakerInitialState:
    def test_initial_state_is_normal(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreakerState.NORMAL

    def test_default_config_values(self):
        cb = CircuitBreaker()
        assert cb.max_daily_loss_pct == 3.0
        assert cb.min_confidence == 0.3
        assert cb.cooldown_minutes == 30
        assert cb.max_consecutive_losses == 5


class TestCircuitBreakerTransitions:
    @pytest.mark.asyncio
    async def test_trip_on_daily_loss_breach(self):
        cb = CircuitBreaker(max_daily_loss_pct=3.0, kill_callback=AsyncMock())
        result = cb.check(daily_pnl_pct=-4.0, confidence_score=0.8, consecutive_losses=0)
        assert result["action"] == "kill_switch"

    @pytest.mark.asyncio
    async def test_trip_on_low_confidence(self):
        cb = CircuitBreaker(min_confidence=0.3, kill_callback=AsyncMock())
        result = cb.check(daily_pnl_pct=0.0, confidence_score=0.1, consecutive_losses=0)
        assert result["action"] == "kill_switch"

    @pytest.mark.asyncio
    async def test_trip_on_consecutive_losses(self):
        cb = CircuitBreaker(max_consecutive_losses=5, kill_callback=AsyncMock())
        result = cb.check(daily_pnl_pct=0.0, confidence_score=0.8, consecutive_losses=6)
        assert result["action"] == "kill_switch"

    def test_normal_conditions_no_action(self):
        cb = CircuitBreaker()
        result = cb.check(daily_pnl_pct=-0.5, confidence_score=0.9, consecutive_losses=1)
        assert result["action"] is None

    @pytest.mark.asyncio
    async def test_cooldown_transitions_back_to_normal(self):
        cb = CircuitBreaker(cooldown_minutes=0)
        await cb.trip("test reason")
        assert cb.state == CircuitBreakerState.COOLDOWN
        cb._tripped_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        result = cb.check(daily_pnl_pct=0.0, confidence_score=0.9, consecutive_losses=0)
        assert cb.state == CircuitBreakerState.NORMAL


class TestCircuitBreakerReset:
    @pytest.mark.asyncio
    async def test_manual_reset(self):
        cb = CircuitBreaker()
        await cb.trip("forced")
        cb.reset()
        assert cb.state == CircuitBreakerState.NORMAL

    def test_get_status_returns_dict(self):
        cb = CircuitBreaker()
        status = cb.get_status()
        assert status["state"] == "NORMAL"
        assert "max_daily_loss_pct" in status
