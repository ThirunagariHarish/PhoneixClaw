import pytest

from services.trade_executor.src.validator import TradeValidator


@pytest.fixture
def validator():
    return TradeValidator()


@pytest.fixture
def valid_trade():
    return {
        "ticker": "SPX",
        "strike": 6940.0,
        "option_type": "CALL",
        "expiration": "2026-02-20",
        "action": "BUY",
        "quantity": 1,
        "price": 4.80,
    }


class TestTradeValidator:
    def test_valid_trade_passes(self, validator, valid_trade):
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is True
        assert error is None

    def test_missing_ticker(self, validator, valid_trade):
        valid_trade["ticker"] = ""
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is False
        assert "Missing required field" in error

    def test_missing_expiration(self, validator, valid_trade):
        valid_trade["expiration"] = None
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is False
        assert "Expiration" in error

    def test_quantity_exceeds_max(self, validator, valid_trade):
        valid_trade["quantity"] = 100
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is False
        assert "exceeds max" in error

    def test_negative_quantity(self, validator, valid_trade):
        valid_trade["quantity"] = -1
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is False

    def test_percentage_quantity_passes(self, validator, valid_trade):
        valid_trade["quantity"] = "50%"
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is True

    def test_zero_price(self, validator, valid_trade):
        valid_trade["price"] = 0
        is_valid, error = validator.validate(valid_trade)
        assert is_valid is False
        assert error is not None

    def test_blacklisted_ticker(self, validator, valid_trade):
        valid_trade["ticker"] = "BADTICKER"
        risk = {"ticker_blacklist": ["BADTICKER"]}
        is_valid, error = validator.validate(valid_trade, risk_config=risk)
        assert is_valid is False
        assert "blacklisted" in error

    def test_trading_disabled(self, validator, valid_trade):
        risk = {"enable_trading": False}
        is_valid, error = validator.validate(valid_trade, risk_config=risk)
        assert is_valid is False
        assert "disabled" in error

    def test_custom_max_position(self, validator, valid_trade):
        valid_trade["quantity"] = 5
        risk = {"max_position_size": 3}
        is_valid, error = validator.validate(valid_trade, risk_config=risk)
        assert is_valid is False
