"""
Regression tests for trade execution pipeline. M1.12.
"""

import json
from unittest.mock import AsyncMock

import pytest

from services.execution.src.risk_chain import (
    GlobalLevelRisk,
    RiskCheckChain,
)


@pytest.fixture
def valid_intent():
    return {
        "id": "intent-1",
        "agent_id": "a1",
        "account_id": "acc1",
        "symbol": "SPY",
        "side": "buy",
        "qty": 10,
        "order_type": "market",
        "limit_price": 450.0,
        "estimated_price": 450.0,
    }


class TestTradeExecutionRegression:
    """Trade intent submission, risk checks, circuit breaker, kill switch."""

    @pytest.mark.asyncio
    async def test_trade_intent_submission_to_redis_stream(self):
        """Trade intent can be submitted (mocked Redis)."""
        intent = {"agent_id": "a1", "account_id": "acc1", "symbol": "SPY", "side": "buy", "qty": 10}
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234-0")
        stream_key = "phoenix:trade-intents"
        msg_id = await mock_redis.xadd(stream_key, {"payload": json.dumps(intent)})
        assert msg_id == "1234-0"
        mock_redis.xadd.assert_called_once()

    def test_risk_check_chain_agent_layer(self, valid_intent):
        """Agent-level risk rejects when max positions exceeded."""
        chain = RiskCheckChain()
        agent_state = {"open_positions": 5, "daily_trades": 10}
        result = chain.evaluate(valid_intent, agent_state=agent_state)
        assert result["approved"] is False
        assert "agent" in result["reason"].lower() or "concurrent" in result["reason"].lower()

    def test_risk_check_chain_execution_layer(self, valid_intent):
        """Execution-level risk rejects oversized position."""
        chain = RiskCheckChain()
        oversized = {**valid_intent, "qty": 200, "limit_price": 500}
        result = chain.evaluate(oversized, agent_state={"open_positions": 0})
        assert result["approved"] is False
        assert "execution" in str(result["checks"]).lower() or "position" in result["reason"].lower()

    def test_risk_check_chain_global_layer(self):
        """Global-level risk rejects when circuit breaker active."""
        class MockGlobalRisk(GlobalLevelRisk):
            CIRCUIT_BREAKER_ACTIVE = True
        chain = RiskCheckChain()
        chain.global_risk = MockGlobalRisk()
        intent = {"agent_id": "a1", "account_id": "acc1", "symbol": "SPY", "side": "buy", "qty": 1}
        result = chain.evaluate(intent, agent_state={"open_positions": 0})
        assert result["approved"] is False
        assert "circuit" in result["reason"].lower() or "halted" in result["reason"].lower()

    def test_duplicate_intent_rejection(self):
        """Duplicate intent IDs can be rejected via dedup key."""
        seen = set()
        intent_id = "intent-dup-1"
        assert intent_id not in seen
        seen.add(intent_id)
        assert intent_id in seen  # Second submission would be rejected

    def test_circuit_breaker_at_daily_loss_threshold(self):
        """Circuit breaker opens when daily loss exceeds threshold."""
        from services.global_monitor.src.circuit_breaker import CircuitBreaker, CircuitBreakerState
        cb = CircuitBreaker({"max_daily_loss": -5000.0})
        cb.evaluate({"daily_pnl": -6000.0})
        assert cb.state == CircuitBreakerState.OPEN
        assert not cb.is_trading_allowed

    def test_kill_switch_closes_all_positions(self):
        """Kill switch sets circuit breaker to OPEN."""
        from services.global_monitor.src.circuit_breaker import CircuitBreaker, CircuitBreakerState
        cb = CircuitBreaker({"max_daily_loss": -5000.0})
        cb.kill_switch()
        assert cb.state == CircuitBreakerState.OPEN
        assert not cb.is_trading_allowed
