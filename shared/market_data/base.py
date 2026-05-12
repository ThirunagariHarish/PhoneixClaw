"""Abstract base class for market data providers.

Defines the contract all market data providers must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

import pandas as pd


class MarketDataProvider(ABC):
    """Abstract base class for market data providers.

    All providers must return DataFrames with a standard schema:
    - Index: pd.DatetimeIndex named "date"
    - Columns: ["open", "high", "low", "close", "adj_close", "volume"]

    Returns empty DataFrames when data is unavailable.
    """

    @abstractmethod
    async def daily_bars(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for a ticker.

        Args:
            ticker: Stock symbol (e.g., "AAPL", "SPY")
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date. Empty DataFrame if no data available.
        """
        ...

    @abstractmethod
    async def intraday_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        interval: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday OHLCV bars for a ticker.

        Args:
            ticker: Stock symbol
            start: Start timestamp (inclusive)
            end: End timestamp (inclusive)
            interval: Bar interval (e.g., "5m", "15m", "1h")

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date. Empty DataFrame if no data available.

        Raises:
            NotImplementedError: If provider doesn't support intraday data
        """
        ...

    def supports_intraday(self) -> bool:
        """Return True if provider supports intraday bars."""
        return True
