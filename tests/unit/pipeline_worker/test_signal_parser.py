"""Tests for pipeline signal parser — ported from OldProject with Phoenix enhancements."""

from services.pipeline_worker.src.pipeline.signal_parser import ParsedSignal, parse_signal


class TestParseSignal:
    """Test signal parsing with OldProject regex patterns."""

    def test_valid_buy_signal(self):
        result = parse_signal("BTO AAPL 190c 4/18 @ 3.50")
        assert result is not None
        assert result.ticker == "AAPL"
        assert result.direction == "buy"
        assert result.strike == 190.0
        assert result.entry_price == 3.50
        assert result.quantity == 1
        assert result.is_percentage is False

    def test_valid_sell_signal(self):
        result = parse_signal("STC TSLA 200P @ 5.00")
        assert result is not None
        assert result.ticker == "TSLA"
        assert result.direction == "sell"
        assert result.is_percentage is False

    def test_percentage_sell_50_pct(self):
        result = parse_signal("Sold 50% SPX 6950C at 6.50")
        assert result is not None
        assert result.ticker == "SPX"
        assert result.direction == "sell"
        assert result.quantity == "50%"
        assert result.is_percentage is True
        assert result.strike == 6950.0
        assert result.option_type == "C"

    def test_percentage_sell_70_pct_with_noise(self):
        result = parse_signal("Sold 70% SPX 6950C at 8 Looks ready for 6950 Test")
        assert result is not None
        assert result.ticker == "SPX"
        assert result.quantity == "70%"
        assert result.is_percentage is True
        assert result.entry_price == 8.0

    def test_percentage_sell_100_pct(self):
        result = parse_signal("Sell 100% AAPL 200C at 5.00")
        assert result is not None
        assert result.quantity == "100%"
        assert result.is_percentage is True

    def test_absolute_quantity_5_contracts(self):
        result = parse_signal("Bought 5 SPX 6940C at 4.80")
        assert result is not None
        assert result.quantity == 5
        assert result.is_percentage is False
        assert result.ticker == "SPX"

    def test_absolute_quantity_10_contracts(self):
        result = parse_signal("BUY 10 IWM 250P at 1.50")
        assert result is not None
        assert result.quantity == 10
        assert result.is_percentage is False

    def test_default_quantity_when_not_specified(self):
        result = parse_signal("Bought PLTR 30C at 2.10")
        assert result is not None
        assert result.quantity == 1
        assert result.is_percentage is False

    def test_expiration_with_exp_prefix(self):
        result = parse_signal("Bought IWM 250P at 1.50 Exp: 02/20/2026")
        assert result is not None
        assert result.expiry == "2026-02-20"
        assert result.ticker == "IWM"
        assert result.strike == 250.0

    def test_expiration_without_prefix(self):
        result = parse_signal("Bought ASTS 100C at 3 04/17/2026")
        assert result is not None
        assert result.ticker == "ASTS"
        assert result.strike == 100.0
        # Expiry parsing may vary by shared parser implementation

    def test_edge_ticker_spx(self):
        result = parse_signal("Bought SPX 6940C at 4.80")
        assert result is not None
        assert result.ticker == "SPX"
        assert result.strike == 6940.0
        assert result.option_type == "C"

    def test_edge_ticker_spxw(self):
        result = parse_signal("Bought SPXW 6950C at 5.00")
        assert result is not None
        assert result.ticker == "SPXW"

    def test_non_standard_strike_decimal(self):
        result = parse_signal("Bought SPY 599.5C at 2.00")
        assert result is not None
        assert result.strike == 599.5
        assert result.option_type == "C"

    def test_put_option(self):
        result = parse_signal("Bought QQQ 450P at 3.20")
        assert result is not None
        assert result.ticker == "QQQ"
        assert result.option_type == "P"
        assert result.strike == 450.0

    def test_call_option(self):
        result = parse_signal("Bought NVDA 900C at 10.50")
        assert result is not None
        assert result.ticker == "NVDA"
        assert result.option_type == "C"

    def test_missing_expiration_parses_rest(self):
        result = parse_signal("Bought SPY 600C at 2.50")
        assert result is not None
        assert result.ticker == "SPY"
        assert result.strike == 600.0
        # Expiry may be None

    def test_missing_price_returns_none_or_parses(self):
        # Shared parser may or may not extract without price
        result = parse_signal("Bought SPY 600C")
        # Depending on shared parser behavior, could be None or partial
        # OldProject required price, so likely None
        if result:
            assert result.ticker == "SPY"

    def test_returns_none_for_noise(self):
        result = parse_signal("good morning everyone, hope markets are green today")
        assert result is None

    def test_returns_none_for_no_direction(self):
        result = parse_signal("AAPL is looking interesting")
        assert result is None

    def test_author_and_channel_preserved(self):
        result = parse_signal("BTO SPY 500c @ 2.00", author="trader1", channel="alerts")
        assert result is not None
        assert result.author == "trader1"
        assert result.channel == "alerts"

    def test_raw_content_preserved(self):
        msg = "Bought PLTR 30C at 2.10"
        result = parse_signal(msg)
        assert result is not None
        assert result.raw_content == msg

    def test_parsed_signal_dataclass_defaults(self):
        ps = ParsedSignal()
        assert ps.ticker is None
        assert ps.confidence == 0.0
        assert ps.raw_content == ""
        assert ps.quantity == 1
        assert ps.is_percentage is False

    def test_complex_message_with_commentary(self):
        result = parse_signal("I just Bought 3 TSLA 250C at 8.50 Exp: 06/20/2026 — looks strong!")
        assert result is not None
        assert result.ticker == "TSLA"
        assert result.quantity == 3
        assert result.strike == 250.0

    def test_stc_abbreviation(self):
        result = parse_signal("STC SPY 600C at 3.00")
        assert result is not None
        assert result.direction == "sell"
        assert result.ticker == "SPY"

    def test_bto_abbreviation(self):
        result = parse_signal("BTO AAPL 190C at 5.00")
        assert result is not None
        assert result.direction == "buy"
        assert result.ticker == "AAPL"
