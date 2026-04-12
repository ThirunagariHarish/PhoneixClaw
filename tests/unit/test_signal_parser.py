"""Comprehensive tests for the intelligent multi-layer signal parser.

Tests cover:
- Various Discord trade signal formats
- Date normalization (numeric, text month, ISO)
- Price disambiguation (entry vs strike vs target vs stop)
- Direction detection (BUY/SELL/close)
- Options parsing (compact, word, date-first, strike-first)
- Edge cases (noise, info, missing fields)
- Backward-compatible wrappers
- Confidence scoring
"""
from datetime import date, datetime

from shared.utils.signal_parser import (
    _extract_entry_price,
    _extract_tickers,
    _normalize_expiry,
    parse_signal_compat,
    parse_signal_transform_compat,
    parse_trade_signal,
)

# ---------------------------------------------------------------------------
# Basic signal format variations
# ---------------------------------------------------------------------------

class TestCommonFormats:
    """Test the most common Discord signal formats."""

    def test_compact_option_format(self):
        """'AAPL 190c 4/18 @ 3.50'"""
        sig = parse_trade_signal("AAPL 190c 4/18 @ 3.50")
        assert sig.ticker == "AAPL"
        assert sig.strike_price == 190.0
        assert sig.option_type == "C"
        assert sig.asset_type == "call"
        assert sig.entry_price == 3.50
        assert sig.expiry_date is not None
        assert sig.expiry_date.endswith("-04-18")

    def test_full_verbose_format(self):
        """'BUY AAPL $190 CALL 4/18/2025 entry 3.50 stop 3.00 target 5.00'"""
        sig = parse_trade_signal(
            "BUY AAPL $190 CALL 4/18/2025 entry 3.50 stop 3.00 target 5.00"
        )
        assert sig.ticker == "AAPL"
        assert sig.direction == "BUY"
        assert sig.strike_price == 190.0
        assert sig.option_type == "C"
        assert sig.entry_price == 3.50
        assert sig.stop_loss == 3.00
        assert sig.take_profit == 5.00
        assert sig.expiry_date == "2025-04-18"

    def test_calls_word_format(self):
        """'AAPL calls $190 strike exp 4/18 looking for 3.50 area'"""
        sig = parse_trade_signal(
            "AAPL calls $190 strike exp 4/18 looking for 3.50 area"
        )
        assert sig.ticker == "AAPL"
        assert sig.option_type == "C"
        assert sig.expiry_date is not None
        assert sig.expiry_date.endswith("-04-18")

    def test_long_format(self):
        """'Long AAPL 190C 4/18'"""
        sig = parse_trade_signal("Long AAPL 190C 4/18")
        assert sig.ticker == "AAPL"
        assert sig.direction == "BUY"
        assert sig.strike_price == 190.0
        assert sig.option_type == "C"
        assert sig.expiry_date is not None

    def test_target_emoji_format(self):
        """'AAPL 4/18 190C target 5.00'"""
        sig = parse_trade_signal("AAPL 4/18 190C target 5.00")
        assert sig.ticker == "AAPL"
        assert sig.strike_price == 190.0
        assert sig.take_profit == 5.00
        assert sig.expiry_date is not None

    def test_bought_text_month_format(self):
        """'Bought AAPL Apr 18 $190 calls at $3.50'"""
        sig = parse_trade_signal("Bought AAPL Apr 18 $190 calls at $3.50")
        assert sig.ticker == "AAPL"
        assert sig.direction == "BUY"
        assert sig.entry_price == 3.50
        assert sig.expiry_date is not None
        assert sig.expiry_date.endswith("-04-18")

    def test_bto_cashtag_format(self):
        """'BTO $AAPL 185c 4/18'"""
        sig = parse_trade_signal("BTO $AAPL 185c 4/18")
        assert sig.ticker == "AAPL"
        assert sig.direction == "BUY"
        assert sig.signal_type == "buy_signal"
        assert sig.strike_price == 185.0
        assert sig.option_type == "C"

    def test_stc_sell_format(self):
        """'STC $TSLA sold at 250'"""
        sig = parse_trade_signal("STC $TSLA sold at 250")
        assert sig.ticker == "TSLA"
        assert sig.direction == "SELL"
        assert sig.signal_type == "sell_signal"

    def test_stock_buy(self):
        """'Buying MSFT at 420.50'"""
        sig = parse_trade_signal("Buying MSFT at 420.50")
        assert sig.ticker == "MSFT"
        assert sig.direction == "BUY"
        assert sig.asset_type == "stock"
        assert sig.entry_price == 420.50

    def test_put_option(self):
        """'SPY 520p 4/19 @ 2.15'"""
        sig = parse_trade_signal("SPY 520p 4/19 @ 2.15")
        assert sig.ticker == "SPY"
        assert sig.strike_price == 520.0
        assert sig.option_type == "P"
        assert sig.asset_type == "put"
        assert sig.entry_price == 2.15


# ---------------------------------------------------------------------------
# Expiry date normalization
# ---------------------------------------------------------------------------

class TestExpiryNormalization:
    def test_numeric_mm_dd(self):
        assert _normalize_expiry("4/18", date(2025, 1, 1)) == "2025-04-18"

    def test_numeric_mm_dd_yy(self):
        assert _normalize_expiry("4/18/25") == "2025-04-18"

    def test_numeric_mm_dd_yyyy(self):
        assert _normalize_expiry("4/18/2025") == "2025-04-18"

    def test_numeric_dash(self):
        assert _normalize_expiry("4-18", date(2025, 1, 1)) == "2025-04-18"

    def test_iso_format(self):
        assert _normalize_expiry("2025-04-18") == "2025-04-18"

    def test_text_month_short(self):
        assert _normalize_expiry("Apr 18", date(2025, 1, 1)) == "2025-04-18"

    def test_text_month_long(self):
        assert _normalize_expiry("April 18", date(2025, 1, 1)) == "2025-04-18"

    def test_text_month_with_year(self):
        assert _normalize_expiry("Apr 18, 2025") == "2025-04-18"

    def test_text_month_with_year_no_comma(self):
        assert _normalize_expiry("April 18 2025") == "2025-04-18"

    def test_empty_returns_none(self):
        assert _normalize_expiry("") is None

    def test_none_returns_none(self):
        assert _normalize_expiry(None) is None

    def test_invalid_returns_none(self):
        assert _normalize_expiry("not a date") is None


# ---------------------------------------------------------------------------
# Price disambiguation
# ---------------------------------------------------------------------------

class TestPriceDisambiguation:
    def test_entry_keyword_preferred(self):
        price = _extract_entry_price("entry 3.50 target 5.00 stop 3.00")
        assert price == 3.50

    def test_at_sign(self):
        price = _extract_entry_price("AAPL 190c @ 3.50")
        assert price == 3.50

    def test_skip_strike_price(self):
        """Should not confuse strike with entry."""
        price = _extract_entry_price("AAPL 190c @ 3.50", strike=190.0)
        assert price == 3.50

    def test_skip_target_price(self):
        price = _extract_entry_price("entry 5.00 target 5.00 stop 3.00", target=5.00)
        # 5.00 matches target, so skip it; no other price found
        assert price is None

    def test_filled_at(self):
        price = _extract_entry_price("filled at 2.85")
        assert price == 2.85

    def test_got_in(self):
        price = _extract_entry_price("got in at 4.20")
        assert price == 4.20

    def test_for_keyword(self):
        price = _extract_entry_price("picked up TSLA 190c for 3.50")
        assert price == 3.50


# ---------------------------------------------------------------------------
# Direction detection
# ---------------------------------------------------------------------------

class TestDirection:
    def test_buy_keywords(self):
        for word in ["BUY", "bought", "Long", "BTO", "entered"]:
            sig = parse_trade_signal(f"{word} $AAPL at 190")
            assert sig.direction == "BUY", f"Failed for '{word}'"

    def test_sell_keywords(self):
        for word in ["SELL", "sold", "STC", "closing", "exited"]:
            sig = parse_trade_signal(f"{word} $AAPL at 190")
            assert sig.direction == "SELL", f"Failed for '{word}'"

    def test_close_signal(self):
        sig = parse_trade_signal("Closed $SPY position, took profit at 500")
        assert sig.signal_type == "close_signal"
        assert sig.direction == "SELL"

    def test_trim_is_sell(self):
        sig = parse_trade_signal("Trimmed 50% $AAPL")
        assert sig.direction == "SELL"

    def test_calls_implies_buy(self):
        sig = parse_trade_signal("$AAPL 190 calls 4/18")
        assert sig.direction == "BUY"
        assert sig.option_type == "C"

    def test_puts_implies_buy(self):
        """Buying puts is still a BUY direction (buy to open)."""
        sig = parse_trade_signal("$SPY 520 puts 4/19")
        assert sig.direction == "BUY"
        assert sig.option_type == "P"


# ---------------------------------------------------------------------------
# Options parsing
# ---------------------------------------------------------------------------

class TestOptions:
    def test_compact_call(self):
        sig = parse_trade_signal("AAPL 190c")
        assert sig.strike_price == 190.0
        assert sig.option_type == "C"
        assert sig.asset_type == "call"

    def test_compact_put(self):
        sig = parse_trade_signal("SPY 520P")
        assert sig.strike_price == 520.0
        assert sig.option_type == "P"
        assert sig.asset_type == "put"

    def test_decimal_strike(self):
        sig = parse_trade_signal("AAPL 190.5c 4/18")
        assert sig.strike_price == 190.5
        assert sig.option_type == "C"

    def test_dollar_strike_word(self):
        sig = parse_trade_signal("AAPL $190 call")
        assert sig.strike_price == 190.0
        assert sig.option_type == "C"

    def test_dollar_strike_word_puts(self):
        sig = parse_trade_signal("SPY $520 puts")
        assert sig.strike_price == 520.0
        assert sig.option_type == "P"

    def test_stock_no_option(self):
        sig = parse_trade_signal("Buying MSFT at 420")
        assert sig.asset_type == "stock"
        assert sig.option_type is None
        assert sig.strike_price is None


# ---------------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------------

class TestTickerExtraction:
    def test_cashtag(self):
        tickers = _extract_tickers("Buying $AAPL today")
        assert "AAPL" in tickers

    def test_option_context(self):
        tickers = _extract_tickers("AAPL 190C 4/18")
        assert "AAPL" in tickers

    def test_multiple_tickers(self):
        tickers = _extract_tickers("$AAPL and $TSLA both looking good")
        assert "AAPL" in tickers
        assert "TSLA" in tickers

    def test_no_common_words(self):
        tickers = _extract_tickers("I AM going TO BUY something")
        assert "AM" not in tickers
        assert "BUY" not in tickers

    def test_deduplication(self):
        tickers = _extract_tickers("$AAPL is great, AAPL 190c")
        assert tickers.count("AAPL") == 1

    def test_empty_message(self):
        tickers = _extract_tickers("")
        assert tickers == []


# ---------------------------------------------------------------------------
# Noise / Info classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_noise(self):
        sig = parse_trade_signal("good morning everyone, happy trading")
        assert sig.signal_type == "noise"
        assert sig.confidence < 0.3

    def test_info_with_ticker(self):
        sig = parse_trade_signal("$NVDA earnings coming up next week")
        assert sig.signal_type == "info"
        assert "NVDA" in sig.tickers

    def test_actionable_buy(self):
        sig = parse_trade_signal("BTO $AAPL 190c 4/18 @ 3.50")
        assert sig.is_actionable

    def test_non_actionable_info(self):
        sig = parse_trade_signal("$AAPL looks interesting today")
        assert not sig.is_actionable


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_full_signal_high_confidence(self):
        sig = parse_trade_signal("BUY $AAPL 190c 4/18/2025 entry 3.50 stop 3.00 target 5.00")
        assert sig.confidence >= 0.8

    def test_partial_signal_medium_confidence(self):
        sig = parse_trade_signal("AAPL 190c 4/18")
        assert 0.3 <= sig.confidence <= 0.7

    def test_noise_low_confidence(self):
        sig = parse_trade_signal("the market is crazy")
        assert sig.confidence < 0.2

    def test_missing_fields_property(self):
        sig = parse_trade_signal("AAPL 190c")
        missing = sig.missing_fields
        assert "entry_price" in missing
        assert "expiry_date" in missing


# ---------------------------------------------------------------------------
# Backward-compatible wrappers
# ---------------------------------------------------------------------------

class TestCompatWrappers:
    def test_parse_signal_compat(self):
        """Test drop-in replacement for live-trader parse()."""
        result = parse_signal_compat({
            "content": "BTO $AAPL 185c 4/18 @ 2.50",
            "author": "vinod",
            "message_id": "123",
        })
        assert result["ticker"] == "AAPL"
        assert result["direction"] == "buy"
        assert result["strike"] == 185.0
        assert result["option_type"] == "call"
        assert result["signal_price"] == 2.50
        assert result["expiry"] is not None
        assert result["author"] == "vinod"

    def test_parse_signal_transform_compat_buy(self):
        """Test drop-in replacement for transform.py parse_signal()."""
        result = parse_signal_transform_compat(
            "BTO $AAPL 190c 4/18/2025 @ 3.50 stop 3.00 target 5.00",
            datetime(2025, 4, 10),
        )
        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["signal_type"] == "buy"
        assert result["price"] == 3.50
        assert result["strike"] == 190.0
        assert result["option_type"] == "call"
        assert result["expiry"] == "2025-04-18"
        assert result["stop_loss"] == 3.00
        assert result["target"] == 5.00
        assert result["trade_type"] == "option"

    def test_transform_compat_returns_none_for_noise(self):
        result = parse_signal_transform_compat(
            "good morning everyone",
            datetime(2025, 4, 10),
        )
        assert result is None

    def test_transform_compat_sell(self):
        result = parse_signal_transform_compat(
            "STC $TSLA sold at 250",
            datetime(2025, 4, 10),
        )
        assert result is not None
        assert result["signal_type"] == "sell"
        assert result["ticker"] == "TSLA"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_spx_index_option(self):
        sig = parse_trade_signal("SPX 5200c 4/18 @ 12.50")
        assert sig.ticker == "SPX"
        assert sig.strike_price == 5200.0
        assert sig.entry_price == 12.50

    def test_fractional_strike(self):
        sig = parse_trade_signal("AAPL 192.5c 4/18")
        assert sig.strike_price == 192.5

    def test_two_digit_year(self):
        sig = parse_trade_signal("AAPL 190c 4/18/25 @ 3.50")
        assert sig.expiry_date == "2025-04-18"

    def test_iso_date_format(self):
        sig = parse_trade_signal("AAPL 190c 2025-04-18 @ 3.50")
        assert sig.expiry_date == "2025-04-18"

    def test_partial_exit(self):
        sig = parse_trade_signal("Trimmed 50% $AAPL at 195")
        assert sig.exit_pct == 0.5
        assert sig.direction == "SELL"

    def test_no_price_still_parses(self):
        sig = parse_trade_signal("Long $NVDA 950c 4/25")
        assert sig.ticker == "NVDA"
        assert sig.direction == "BUY"
        assert sig.strike_price == 950.0
        assert sig.entry_price is None  # No explicit price

    def test_text_month_april(self):
        sig = parse_trade_signal("Bought AAPL April 18 $190 calls at $3.50")
        assert sig.ticker == "AAPL"
        assert sig.expiry_date is not None
        assert sig.expiry_date.endswith("-04-18")

    def test_text_month_january(self):
        sig = parse_trade_signal("AAPL Jan 17 190c")
        assert sig.expiry_date is not None
        assert "-01-17" in sig.expiry_date

    def test_as_of_date_for_year(self):
        sig = parse_trade_signal("AAPL 190c 4/18", as_of_date=date(2026, 3, 1))
        assert sig.expiry_date == "2026-04-18"

    def test_stop_and_target_not_confused_with_entry(self):
        sig = parse_trade_signal(
            "BUY $AAPL 190c entry 3.50 stop 3.00 target 5.00"
        )
        assert sig.entry_price == 3.50
        assert sig.stop_loss == 3.00
        assert sig.take_profit == 5.00

    def test_empty_string(self):
        sig = parse_trade_signal("")
        assert sig.signal_type == "noise"
        assert sig.confidence < 0.1

    def test_parsed_signal_to_dict(self):
        sig = parse_trade_signal("BTO $AAPL 190c 4/18 @ 3.50")
        d = sig.to_dict()
        assert "ticker" in d
        assert "raw_message" in d
