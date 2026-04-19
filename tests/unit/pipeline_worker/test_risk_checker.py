"""Tests for risk checker — enhanced with OldProject validation patterns."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import only the necessary items without triggering model imports
import sys
sys.path.insert(0, "/Users/harishkumar/Projects/TradingBot/ProjectPhoneix/services/pipeline-worker/src")

from pipeline.risk_checker import (
    DEFAULT_TICKER_BLACKLIST,
    RiskCheck,
    RiskResult,
    check_risk,
)


def _mock_session(open_position_count: int = 0, total_contracts: int = 0, position_qty: int = 0):
    """Create a mock async session with configurable query responses."""
    session = AsyncMock()
    call_count = {"count": 0}

    async def execute_side_effect(query):
        """Return different mock results based on query type."""
        mock_result = MagicMock()
        call_count["count"] += 1

        # Return values in sequence: open_position_count, total_contracts, position_qty
        if call_count["count"] == 1:
            mock_result.scalar_one.return_value = open_position_count
        elif call_count["count"] == 2:
            mock_result.scalar_one.return_value = total_contracts or None
        else:
            mock_result.scalar_one.return_value = position_qty or None

        return mock_result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    return session


class TestCheckRisk:
    """Test risk validation with OldProject patterns."""

    @pytest.mark.asyncio
    async def test_all_checks_pass(self):
        """Test all checks pass - using SELL to avoid DB model imports."""
        signal = {
            "ticker": "AAPL",
            "direction": "SELL",  # Use SELL to skip BUY-only checks
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": 1,
            "is_percentage": False,
        }
        prediction = {"confidence": 0.8}
        config = {
            "risk_params": {"confidence_threshold": 0.6, "max_concurrent_positions": 5},
            "buying_power": 10000.0,
        }

        # Mock without position_qty since it's not percentage sell
        session = _mock_session(open_position_count=2)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is True
        assert result.reason == ""
        # SELL without percentage: ticker_blacklist, required_fields, confidence, max_position_size, max_concurrent, daily_loss
        assert len(result.checks) >= 6

    @pytest.mark.asyncio
    async def test_ticker_blacklist_rejection(self):
        signal = {
            "ticker": "UVXY",
            "direction": "BUY",
            "price": 5.00,
            "strike": 20.0,
            "option_type": "C",
            "expiry": "2026-04-18",
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {}}
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "ticker_blacklist"
        assert "UVXY" in result.checks[0].detail

    @pytest.mark.asyncio
    async def test_custom_blacklist(self):
        signal = {
            "ticker": "GME",
            "direction": "BUY",
            "price": 5.00,
            "strike": 20.0,
            "option_type": "C",
            "expiry": "2026-04-18",
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {"ticker_blacklist": ["GME", "AMC"]}}
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "ticker_blacklist"

    @pytest.mark.asyncio
    async def test_missing_required_fields(self):
        signal = {"ticker": "AAPL", "direction": "BUY"}  # Missing price, strike, expiry
        prediction = {"confidence": 0.9}
        config = {}
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "required_fields"

    @pytest.mark.asyncio
    async def test_confidence_below_threshold(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
        }
        prediction = {"confidence": 0.3}
        config = {"risk_params": {"confidence_threshold": 0.6}}
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "confidence_threshold"

    @pytest.mark.asyncio
    async def test_percentage_sell_no_position(self):
        signal = {
            "ticker": "SPX",
            "direction": "SELL",
            "price": 6.50,
            "strike": 6950.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": "50%",
            "is_percentage": True,
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {}}
        session = _mock_session(position_qty=0)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "percentage_sell_position"

    @pytest.mark.asyncio
    async def test_percentage_sell_with_position(self):
        signal = {
            "ticker": "SPX",
            "direction": "SELL",
            "price": 6.50,
            "strike": 6950.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": "50%",
            "is_percentage": True,
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {}}
        session = _mock_session(open_position_count=1, position_qty=10)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        # Should pass percentage_sell_position check
        checks_dict = {c.name: c for c in result.checks}
        assert checks_dict["percentage_sell_position"].passed is True

    @pytest.mark.asyncio
    async def test_max_position_size_exceeded(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": 15,
            "is_percentage": False,
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {"max_position_size": 10}, "buying_power": 100000.0}
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "max_position_size"

    @pytest.mark.asyncio
    async def test_max_positions_exceeded(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {"max_concurrent_positions": 3}, "buying_power": 10000.0}
        session = _mock_session(open_position_count=3)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "max_concurrent_positions"

    @pytest.mark.asyncio
    async def test_max_total_contracts_exceeded(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": 10,
            "is_percentage": False,
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {"max_total_contracts": 50}, "buying_power": 100000.0}
        session = _mock_session(open_position_count=1, total_contracts=45)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "max_total_contracts"

    @pytest.mark.asyncio
    async def test_daily_loss_exceeded(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
        }
        prediction = {"confidence": 0.9}
        config = {
            "risk_params": {"max_daily_loss_pct": 5.0},
            "daily_pnl_pct": -6.0,
            "buying_power": 10000.0,
        }
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "max_daily_loss_pct"

    @pytest.mark.asyncio
    async def test_insufficient_buying_power(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 10.00,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": 10,
            "is_percentage": False,
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {}, "buying_power": 500.0}  # Need 10*10*100 = 10,000
        session = _mock_session(total_contracts=0)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        assert result.approved is False
        assert result.reason == "buying_power"

    @pytest.mark.asyncio
    async def test_sufficient_buying_power(self):
        signal = {
            "ticker": "AAPL",
            "direction": "BUY",
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
            "quantity": 1,
            "is_percentage": False,
        }
        prediction = {"confidence": 0.9}
        config = {"risk_params": {}, "buying_power": 10000.0}  # Need 1*3.5*100 = 350
        session = _mock_session(total_contracts=0)

        result = await check_risk(signal, prediction, "agent-1", config, session)
        checks_dict = {c.name: c for c in result.checks}
        assert checks_dict["buying_power"].passed is True

    @pytest.mark.asyncio
    async def test_default_config_values(self):
        signal = {
            "ticker": "AAPL",
            "direction": "SELL",  # Use SELL to avoid buying_power and total_contracts checks
            "price": 3.50,
            "strike": 190.0,
            "option_type": "C",
            "expiry": "2026-04-18",
        }
        prediction = {"confidence": 0.7}
        config = {}
        session = _mock_session()

        result = await check_risk(signal, prediction, "agent-1", config, session)
        # SELL orders skip buying_power and total_contracts checks
        assert len(result.checks) >= 6

    def test_risk_result_dataclass(self):
        rr = RiskResult(approved=True, reason="")
        assert rr.checks == []

    def test_risk_check_dataclass(self):
        rc = RiskCheck(name="test", passed=True, detail="ok")
        assert rc.name == "test"

    def test_default_blacklist_contains_volatility_tickers(self):
        assert "UVXY" in DEFAULT_TICKER_BLACKLIST
        assert "VXX" in DEFAULT_TICKER_BLACKLIST
        assert "SQQQ" in DEFAULT_TICKER_BLACKLIST
