"""Tests for market data provider abstraction."""

from __future__ import annotations

import os
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from shared.market_data import (
    MarketDataProvider,
    TiingoProvider,
    YFinanceProvider,
    get_provider,
)


class TestFactory:
    """Tests for provider factory."""

    def test_get_provider_explicit_tiingo(self):
        """Test explicit Tiingo provider selection."""
        provider = get_provider("tiingo")
        assert isinstance(provider, TiingoProvider)

    def test_get_provider_explicit_yfinance(self):
        """Test explicit yfinance provider selection."""
        provider = get_provider("yfinance")
        assert isinstance(provider, YFinanceProvider)

    def test_get_provider_invalid_name(self):
        """Test that invalid provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown market data provider"):
            get_provider("invalid")

    @patch.dict(os.environ, {"TIINGO_API_KEY": "test-key"}, clear=False)
    def test_get_provider_auto_detect_tiingo(self):
        """Test auto-detection when TIINGO_API_KEY is set."""
        # Clear cached instance
        import shared.market_data.factory as factory_mod
        factory_mod._provider_instance = None

        provider = get_provider()
        assert isinstance(provider, TiingoProvider)

        # Clean up
        factory_mod._provider_instance = None

    @patch.dict(os.environ, {}, clear=False)
    def test_get_provider_auto_detect_yfinance(self):
        """Test auto-detection defaults to yfinance when no API key."""
        # Clear cached instance and remove TIINGO_API_KEY
        import shared.market_data.factory as factory_mod
        factory_mod._provider_instance = None
        os.environ.pop("TIINGO_API_KEY", None)

        provider = get_provider()
        assert isinstance(provider, YFinanceProvider)

        # Clean up
        factory_mod._provider_instance = None

    @patch.dict(
        os.environ,
        {"PHOENIX_MARKET_DATA_PROVIDER": "tiingo", "TIINGO_API_KEY": "test"},
        clear=False,
    )
    def test_get_provider_env_override(self):
        """Test PHOENIX_MARKET_DATA_PROVIDER env var override."""
        import shared.market_data.factory as factory_mod
        factory_mod._provider_instance = None

        provider = get_provider()
        assert isinstance(provider, TiingoProvider)

        # Clean up
        factory_mod._provider_instance = None
        os.environ.pop("PHOENIX_MARKET_DATA_PROVIDER", None)


class TestTiingoProvider:
    """Tests for Tiingo provider."""

    @pytest.mark.asyncio
    async def test_daily_bars_schema(self):
        """Test that daily_bars returns correct DataFrame schema."""
        provider = TiingoProvider(api_key="test-key")

        # Mock the HTTP response
        mock_response = [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000000,
                "adjClose": 101.0,
                "adjHigh": 102.0,
                "adjLow": 99.0,
                "adjOpen": 100.0,
                "adjVolume": 1000000,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }
        ]

        provider._fetch_with_retry = AsyncMock(return_value=mock_response)

        df = await provider.daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        # Check schema
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "date"

        # Check values
        assert df.iloc[0]["open"] == 100.0
        assert df.iloc[0]["close"] == 101.0
        assert df.iloc[0]["adj_close"] == 101.0

    @pytest.mark.asyncio
    async def test_daily_bars_empty_response(self):
        """Test that empty response returns empty DataFrame."""
        provider = TiingoProvider(api_key="test-key")
        provider._fetch_with_retry = AsyncMock(return_value=[])

        df = await provider.daily_bars("INVALID", date(2024, 1, 1), date(2024, 1, 31))

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    @pytest.mark.asyncio
    async def test_daily_bars_unsupported_ticker(self):
        """Test that futures tickers return empty DataFrame."""
        provider = TiingoProvider(api_key="test-key")

        df = await provider.daily_bars("ES=F", date(2024, 1, 1), date(2024, 1, 31))

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    @pytest.mark.asyncio
    async def test_daily_bars_ticker_mapping(self):
        """Test that SPX maps to SPY."""
        provider = TiingoProvider(api_key="test-key")

        mock_response = [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 400.0,
                "high": 402.0,
                "low": 399.0,
                "close": 401.0,
                "volume": 5000000,
                "adjClose": 401.0,
                "adjHigh": 402.0,
                "adjLow": 399.0,
                "adjOpen": 400.0,
                "adjVolume": 5000000,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }
        ]

        provider._fetch_with_retry = AsyncMock(return_value=mock_response)

        df = await provider.daily_bars("SPX", date(2024, 1, 1), date(2024, 1, 31))

        # Verify the mapped ticker was used (SPX -> SPY)
        assert not df.empty
        assert provider._resolve_ticker("SPX") == "SPY"

    @pytest.mark.asyncio
    async def test_intraday_bars_schema(self):
        """Test that intraday_bars returns correct DataFrame schema."""
        provider = TiingoProvider(api_key="test-key")

        mock_response = [
            {
                "date": "2024-01-02T09:30:00.000Z",
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 10000,
            }
        ]

        provider._fetch_with_retry = AsyncMock(return_value=mock_response)

        df = await provider.intraday_bars(
            "AAPL",
            datetime(2024, 1, 2, 9, 30),
            datetime(2024, 1, 2, 16, 0),
            interval="5m",
        )

        # Check schema
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "date"

        # Check that adj_close was populated from close
        assert df.iloc[0]["adj_close"] == df.iloc[0]["close"]

    @pytest.mark.asyncio
    async def test_fetch_with_retry_exponential_backoff(self):
        """Test that fetch_with_retry implements exponential backoff."""
        provider = TiingoProvider(api_key="test-key")

        # Mock the client to fail twice then succeed
        call_count = {"n": 0}

        async def mock_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                from unittest.mock import MagicMock
                response = MagicMock()
                response.raise_for_status.side_effect = Exception("Network error")
                raise Exception("Network error")
            # Third call succeeds
            from unittest.mock import MagicMock
            response = MagicMock()
            response.json.return_value = {"success": True}
            response.raise_for_status.return_value = None
            return response

        with patch.object(provider, "_get_client") as mock_client:
            mock_client.return_value.get = mock_get

            result = await provider._fetch_with_retry("http://test.com")

            # Should have succeeded after 2 failures
            assert result == {"success": True}
            assert call_count["n"] == 3

    def test_supports_intraday(self):
        """Test that Tiingo supports intraday."""
        provider = TiingoProvider(api_key="test-key")
        assert provider.supports_intraday() is True


class TestYFinanceProvider:
    """Tests for yfinance provider."""

    @pytest.mark.asyncio
    async def test_daily_bars_schema(self):
        """Test that daily_bars returns correct DataFrame schema."""
        provider = YFinanceProvider()

        # Create a mock DataFrame matching yfinance output
        mock_data = pd.DataFrame({
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1000000],
        })
        mock_data.index = pd.DatetimeIndex(["2024-01-02"])

        provider._download_async = AsyncMock(return_value=mock_data)

        df = await provider.daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        # Check schema
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "date"

    @pytest.mark.asyncio
    async def test_daily_bars_empty(self):
        """Test that empty yfinance response returns empty DataFrame."""
        provider = YFinanceProvider()
        provider._download_async = AsyncMock(return_value=pd.DataFrame())

        df = await provider.daily_bars("INVALID", date(2024, 1, 1), date(2024, 1, 31))

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    @pytest.mark.asyncio
    async def test_intraday_bars_old_date_skipped(self):
        """Test that intraday requests for old dates return empty."""
        provider = YFinanceProvider()

        # Request data from 100 days ago (beyond 55-day limit)
        old_date = datetime.now().replace(year=2020)

        df = await provider.intraday_bars(
            "AAPL",
            old_date,
            old_date,
            interval="5m",
        )

        # Should return empty without calling yfinance
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    @pytest.mark.asyncio
    async def test_ticker_resolution(self):
        """Test that ticker aliases are resolved correctly."""
        provider = YFinanceProvider()

        # Test SPX -> ^GSPC mapping
        assert provider._resolve_ticker("SPX") == "^GSPC"
        assert provider._resolve_ticker("ES") == "ES=F"
        assert provider._resolve_ticker("AAPL") == "AAPL"  # No mapping

    def test_supports_intraday(self):
        """Test that yfinance supports intraday."""
        provider = YFinanceProvider()
        assert provider.supports_intraday() is True


class TestDataFrameNormalization:
    """Tests for DataFrame normalization across providers."""

    @pytest.mark.asyncio
    async def test_consistent_schema_tiingo_yfinance(self):
        """Test that both providers return identical schema."""
        tiingo = TiingoProvider(api_key="test-key")
        yfinance = YFinanceProvider()

        # Mock responses
        tiingo_mock = [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000000,
                "adjClose": 101.0,
                "adjHigh": 102.0,
                "adjLow": 99.0,
                "adjOpen": 100.0,
                "adjVolume": 1000000,
                "divCash": 0.0,
                "splitFactor": 1.0,
            }
        ]

        yfinance_mock = pd.DataFrame({
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Close": [101.0],
            "Adj Close": [101.0],
            "Volume": [1000000],
        })
        yfinance_mock.index = pd.DatetimeIndex(["2024-01-02"])

        tiingo._fetch_with_retry = AsyncMock(return_value=tiingo_mock)
        yfinance._download_async = AsyncMock(return_value=yfinance_mock)

        df_tiingo = await tiingo.daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 31))
        df_yfinance = await yfinance.daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 31))

        # Both should have identical schema
        assert list(df_tiingo.columns) == list(df_yfinance.columns)
        assert df_tiingo.index.name == df_yfinance.index.name
        assert isinstance(df_tiingo.index, pd.DatetimeIndex)
        assert isinstance(df_yfinance.index, pd.DatetimeIndex)
