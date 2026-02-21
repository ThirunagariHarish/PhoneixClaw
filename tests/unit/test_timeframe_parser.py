from services.trade_parser.src.parser import extract_timeframe, parse_trade_message


class TestExtractTimeframe:
    def test_0dte(self):
        result = extract_timeframe("BTO SPX 6000C 0DTE @ 2.50")
        assert result is not None
        assert result["label"] == "0DTE"
        assert result["days_offset"] == 0

    def test_weekly(self):
        result = extract_timeframe("weekly calls on AAPL")
        assert result is not None
        assert result["label"] == "WEEKLY"
        assert result["days_offset"] == 5

    def test_monthly(self):
        result = extract_timeframe("monthly put on SPY")
        assert result is not None
        assert result["label"] == "MONTHLY"
        assert result["days_offset"] == 30

    def test_leaps(self):
        result = extract_timeframe("LEAPS on MSFT")
        assert result is not None
        assert result["label"] == "LEAPS"
        assert result["days_offset"] == 365

    def test_4hr(self):
        result = extract_timeframe("quick 4hr play")
        assert result is not None
        assert result["label"] == "4HR"
        assert result["days_offset"] == 0

    def test_2_week(self):
        result = extract_timeframe("2 week out on TSLA")
        assert result is not None
        assert result["days_offset"] == 14

    def test_3_day(self):
        result = extract_timeframe("3 day hold")
        assert result is not None
        assert result["days_offset"] == 3

    def test_no_timeframe(self):
        result = extract_timeframe("Just a regular message")
        assert result is None

    def test_parse_message_inferred_expiration(self):
        result = parse_trade_message("Bought SPX 6000C at 2.50 weekly play")
        assert len(result["actions"]) == 1
        assert "timeframe" in result
        assert result["timeframe"]["label"] == "WEEKLY"

    def test_explicit_exp_takes_priority(self):
        result = parse_trade_message("BTO AAPL 190C 3/21 @ 2.50 weekly")
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert "03-21" in action["expiration"]
