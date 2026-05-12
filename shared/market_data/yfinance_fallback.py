"""yfinance fallback provider.

Wraps yfinance for backward compatibility. Has known limitations:
- Rate limited and unreliable
- Only 60 days of intraday data
- Slow network round-trips

Use TiingoProvider for production where possible.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

import pandas as pd

from .base import MarketDataProvider

logger = logging.getLogger(__name__)

# Import the ticker alias map from the backtesting enrich tool
# This map is the source of truth for yfinance ticker aliases
try:
    import sys
    from pathlib import Path
    # Add agents/backtesting/tools to path so we can import the map
    tools_path = Path(__file__).parent.parent.parent / "agents" / "backtesting" / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))
    from enrich import _TICKER_ALIAS_MAP
except ImportError:
    # Fallback if enrich.py not available (e.g., in isolated tests)
    logger.warning("Could not import _TICKER_ALIAS_MAP from enrich.py, using inline copy")
    _TICKER_ALIAS_MAP = {
        # Indices — yfinance needs the ^ prefix
        "SPX": "^GSPC", "SPXW": "^GSPC", "GSPC": "^GSPC",
        "NDX": "^NDX", "DJI": "^DJI", "DJIA": "^DJI",
        "RUT": "^RUT", "VIX": "^VIX", "VVIX": "^VVIX",
        # Front-month futures — yfinance needs the =F suffix
        "ES": "ES=F", "NQ": "NQ=F", "YM": "YM=F", "RTY": "RTY=F",
        "MES": "MES=F", "MNQ": "MNQ=F", "MYM": "MYM=F", "M2K": "M2K=F",
        "CL": "CL=F", "GC": "GC=F", "SI": "SI=F", "NG": "NG=F", "ZB": "ZB=F",
        # Crypto front-month / spot
        "BTC": "BTC-USD", "ETH": "ETH-USD",
    }

# yfinance only serves 5-minute bars for the most recent ~60 days
YF_INTRADAY_MAX_AGE_DAYS = 55


class YFinanceProvider(MarketDataProvider):
    """yfinance market data provider.

    Wraps yfinance.download() in async via run_in_executor.
    Handles ticker aliasing for indices, futures, and crypto.
    """

    def __init__(self):
        """Initialize yfinance provider."""
        pass

    def _resolve_ticker(self, ticker: str) -> str:
        """Map ticker to yfinance-compatible symbol.

        Returns:
            Mapped ticker (or original if no mapping exists)
        """
        if not ticker:
            return ticker
        return _TICKER_ALIAS_MAP.get(ticker.upper(), ticker)

    async def _download_async(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Download data via yfinance in an executor thread.

        Args:
            ticker: Symbol to download
            start: Start date string (YYYY-MM-DD)
            end: End date string (YYYY-MM-DD)
            interval: Bar interval (1d, 5m, 1h, etc.)

        Returns:
            DataFrame with yfinance schema (will be normalized by caller)
        """
        import yfinance as yf

        def _download():
            try:
                data = yf.download(
                    ticker,
                    start=start,
                    end=end,
                    interval=interval,
                    progress=False,
                )
                # yfinance sometimes returns MultiIndex columns for single ticker
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                return data
            except Exception as e:
                logger.error(
                    "yfinance download failed for %s (%s -> %s): %s",
                    ticker,
                    start,
                    end,
                    e,
                )
                return pd.DataFrame()

        return await asyncio.to_thread(_download)

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize yfinance DataFrame to standard schema.

        Args:
            df: Raw yfinance DataFrame

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date with name "date"
        """
        if df.empty:
            return pd.DataFrame()

        # yfinance returns: Open, High, Low, Close, Adj Close, Volume
        # Normalize column names
        df.columns = df.columns.str.lower().str.replace(" ", "_")

        # Ensure required columns exist
        required = ["open", "high", "low", "close", "adj_close", "volume"]
        for col in required:
            if col not in df.columns:
                df[col] = 0.0

        df = df[required]

        # Ensure index is DatetimeIndex with name "date"
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index.name = "date"

        return df

    async def daily_bars(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars via yfinance.

        Args:
            ticker: Stock symbol
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date. Empty DataFrame if no data available.
        """
        resolved = self._resolve_ticker(ticker)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        df = await self._download_async(resolved, start_str, end_str, interval="1d")

        if df.empty:
            label = ticker if resolved == ticker else f"{ticker} (resolved={resolved})"
            logger.debug(
                "yfinance returned empty daily bars for %s (%s -> %s)",
                label,
                start_str,
                end_str,
            )

        return self._normalize_dataframe(df)

    async def intraday_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        interval: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday OHLCV bars via yfinance.

        Args:
            ticker: Stock symbol
            start: Start timestamp (inclusive)
            end: End timestamp (inclusive)
            interval: Bar interval (e.g., "5m", "15m", "1h")

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date. Empty DataFrame if date range > 60 days or no data.

        Note:
            yfinance only serves intraday data for the most recent ~60 days.
            Returns empty DataFrame for older date ranges.
        """
        resolved = self._resolve_ticker(ticker)

        # Check if date range is within yfinance's intraday limit
        age_days = (datetime.now() - start).days
        if age_days > YF_INTRADAY_MAX_AGE_DAYS:
            logger.debug(
                "yfinance intraday request skipped for %s - too old (%d days > %d)",
                ticker,
                age_days,
                YF_INTRADAY_MAX_AGE_DAYS,
            )
            return pd.DataFrame()

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        df = await self._download_async(resolved, start_str, end_str, interval=interval)

        if df.empty:
            label = ticker if resolved == ticker else f"{ticker} (resolved={resolved})"
            logger.debug(
                "yfinance returned empty intraday bars for %s (%s -> %s)",
                label,
                start_str,
                end_str,
            )

        return self._normalize_dataframe(df)

    def supports_intraday(self) -> bool:
        """Return True - yfinance supports intraday (with 60-day limit)."""
        return True
