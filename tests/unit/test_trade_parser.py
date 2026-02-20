
from services.trade_parser.src.parser import parse_trade_message


class TestParseTradeMessage:
    def test_buy_with_expiration(self):
        result = parse_trade_message("Bought IWM 250P at 1.50 Exp: 02/20/2026")
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "BUY"
        assert action["ticker"] == "IWM"
        assert action["strike"] == 250.0
        assert action["option_type"] == "PUT"
        assert action["price"] == 1.50
        assert action["expiration"] == "2026-02-20"
        assert action["quantity"] == 1
        assert action["is_percentage"] is False

    def test_buy_without_expiration(self):
        result = parse_trade_message("Bought SPX 6940C at 4.80")
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "BUY"
        assert action["ticker"] == "SPX"
        assert action["strike"] == 6940.0
        assert action["option_type"] == "CALL"
        assert action["price"] == 4.80

    def test_sell_percentage(self):
        result = parse_trade_message("Sold 50% SPX 6950C at 6.50")
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "SELL"
        assert action["ticker"] == "SPX"
        assert action["quantity"] == "50%"
        assert action["is_percentage"] is True
        assert action["price"] == 6.50

    def test_sell_with_trailing_text(self):
        result = parse_trade_message("Sold 70% SPX 6950C at 8 Looks ready for 6950 Test")
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["action"] == "SELL"
        assert action["price"] == 8.0
        assert action["quantity"] == "70%"

    def test_buy_with_quantity(self):
        result = parse_trade_message("Bought 5 SPX 6940C at 4.80")
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["quantity"] == 5
        assert action["is_percentage"] is False

    def test_no_trade_found(self):
        result = parse_trade_message("Hey everyone, market looks bullish today!")
        assert len(result["actions"]) == 0

    def test_raw_message_preserved(self):
        msg = "Bought SPX 6940C at 4.80"
        result = parse_trade_message(msg)
        assert result["raw_message"] == msg

    def test_call_option(self):
        result = parse_trade_message("Buy AAPL 190C at 3.50")
        assert len(result["actions"]) == 1
        assert result["actions"][0]["option_type"] == "CALL"

    def test_put_option(self):
        result = parse_trade_message("Buy AAPL 180P at 2.80")
        assert len(result["actions"]) == 1
        assert result["actions"][0]["option_type"] == "PUT"

    def test_decimal_strike(self):
        result = parse_trade_message("Bought TSLA 250.5C at 5.00")
        assert len(result["actions"]) == 1
        assert result["actions"][0]["strike"] == 250.5

    def test_dollar_sign_price(self):
        result = parse_trade_message("Bought SPY 500C at $3.50")
        assert len(result["actions"]) == 1
        assert result["actions"][0]["price"] == 3.50

    def test_case_insensitive(self):
        result = parse_trade_message("bought spx 6940c at 4.80")
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "BUY"
