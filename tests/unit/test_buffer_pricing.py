import pytest

from services.trade_executor.src.buffer import calculate_buffered_price


class TestBufferPricing:
    def test_buy_buffer_increases_price(self):
        buffered, pct = calculate_buffered_price(10.0, "BUY")
        assert buffered > 10.0

    def test_sell_buffer_decreases_price(self):
        buffered, pct = calculate_buffered_price(10.0, "SELL")
        assert buffered < 10.0

    def test_default_buffer_percentage(self):
        buffered, pct = calculate_buffered_price(100.0, "BUY")
        assert buffered == pytest.approx(115.0, rel=0.01)

    def test_custom_buffer_percentage(self):
        buffered, pct = calculate_buffered_price(100.0, "BUY", buffer_pct=0.10)
        assert buffered == pytest.approx(110.0, rel=0.01)

    def test_buffer_min_price_floor(self):
        buffered, pct = calculate_buffered_price(0.05, "BUY")
        assert buffered > 0.05  # buffer applied on top of price

    def test_sell_never_goes_below_min(self):
        buffered, pct = calculate_buffered_price(0.02, "SELL")
        assert buffered >= 0.01

    def test_returns_buffer_pct_used(self):
        _, pct = calculate_buffered_price(100.0, "BUY")
        assert pct > 0
        assert pct <= 0.30

    def test_zero_price(self):
        buffered, pct = calculate_buffered_price(0.0, "BUY")
        assert buffered >= 0.01

    def test_precision(self):
        buffered, _ = calculate_buffered_price(4.80, "BUY")
        assert buffered == round(buffered, 2)
