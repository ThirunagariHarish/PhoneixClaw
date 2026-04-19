"""Tests for ta_analyzer module."""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from services.pipeline_worker.src.pipeline.ta_analyzer import (
    TAResult,
    _adx,
    _bb_position,
    _compute_ta,
    _macd_signal,
    _rsi,
    analyze,
)


def _make_price_data(n: int = 30, start: float = 100.0, trend: float = 0.5) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    close = start + np.cumsum(np.random.randn(n) * 2 + trend)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    volume = np.random.randint(1_000_000, 10_000_000, n).astype(float)
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


class TestIndicators:
    def test_rsi_range(self):
        data = _make_price_data(50)
        val = _rsi(data["Close"], 14)
        assert 0 <= val <= 100

    def test_macd_signal_values(self):
        data = _make_price_data(50)
        result = _macd_signal(data["Close"])
        assert result in ("bullish", "bearish", "neutral")

    def test_bb_position_values(self):
        data = _make_price_data(50)
        result = _bb_position(data["Close"])
        assert result in ("above", "below", "within")

    def test_adx_non_negative(self):
        data = _make_price_data(50)
        val = _adx(data["High"], data["Low"], data["Close"])
        assert val >= 0


class TestComputeTA:
    @patch("services.pipeline_worker.src.pipeline.ta_analyzer.yf")
    def test_returns_ta_result(self, mock_yf):
        data = _make_price_data(50)
        mock_yf.download.return_value = data

        result = _compute_ta("AAPL")
        assert isinstance(result, TAResult)
        assert result.rsi is not None
        assert result.overall_bias in ("bullish", "bearish", "neutral")
        assert -0.2 <= result.confidence_adjustment <= 0.2

    @patch("services.pipeline_worker.src.pipeline.ta_analyzer.yf")
    def test_returns_default_on_empty_data(self, mock_yf):
        mock_yf.download.return_value = pd.DataFrame()
        result = _compute_ta("FAKE")
        assert result.rsi is None
        assert result.overall_bias == "neutral"

    @patch("services.pipeline_worker.src.pipeline.ta_analyzer.yf")
    def test_returns_default_on_exception(self, mock_yf):
        mock_yf.download.side_effect = Exception("network error")
        result = _compute_ta("AAPL")
        assert result.rsi is None


class TestAnalyze:
    @pytest.mark.asyncio
    @patch("services.pipeline_worker.src.pipeline.ta_analyzer._compute_ta")
    async def test_runs_in_executor(self, mock_compute):
        mock_compute.return_value = TAResult(rsi=55.0, overall_bias="bullish")
        result = await analyze("AAPL")
        assert result.rsi == 55.0
        mock_compute.assert_called_once_with("AAPL")
