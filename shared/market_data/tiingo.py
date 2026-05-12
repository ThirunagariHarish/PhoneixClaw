"""Tiingo market data provider.

Uses Tiingo's REST API for daily and intraday OHLCV bars.
Free tier: 1000 requests/hour, 20 years of daily data, ~30 days of intraday.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime

import httpx
import pandas as pd

from .base import MarketDataProvider

logger = logging.getLogger(__name__)


# Tiingo doesn't serve raw index or futures data on free tier. Map to equivalent ETFs.
_TIINGO_TICKER_MAP = {
    "SPX": "SPY",
    "SPXW": "SPY",
    "^GSPC": "SPY",
    "NDX": "QQQ",
    "^NDX": "QQQ",
    "^DJI": "DIA",
    "DJI": "DIA",
    "DJIA": "DIA",
    "^RUT": "IWM",
    "RUT": "IWM",
    "^VIX": "VXX",  # VIX ETN proxy
    "VIX": "VXX",
    # Futures are not supported on Tiingo free tier - return empty
    "ES=F": None,
    "NQ=F": None,
    "YM=F": None,
    "RTY=F": None,
    "MES=F": None,
    "MNQ=F": None,
    "MYM=F": None,
    "M2K=F": None,
    "CL=F": None,
    "GC=F": None,
    "SI=F": None,
    "NG=F": None,
    "ZB=F": None,
}


class TiingoProvider(MarketDataProvider):
    """Tiingo market data provider.

    Uses httpx.AsyncClient for HTTP calls with retries and exponential backoff.
    """

    def __init__(self, api_key: str | None = None):
        """Initialize Tiingo provider.

        Args:
            api_key: Tiingo API key. If None, resolved lazily at first request
                via env var TIINGO_API_KEY first, then api_keys table
                (provider="tiingo", name="tiingo_api_key"). This means the
                operator can rotate the key from the admin UI without
                restarting any pod.
        """
        self._explicit_api_key = api_key
        self._cached_api_key: str | None = None

        self._base_url = "https://api.tiingo.com"
        self._timeout = 30.0
        self._max_retries = 3
        self._client: httpx.AsyncClient | None = None
        self._client_key: str | None = None  # which key the current client was built with

    @property
    def api_key(self) -> str:
        """Synchronous read for tests / callers that already know the key was injected."""
        return self._explicit_api_key or self._cached_api_key or os.getenv("TIINGO_API_KEY", "")

    async def _resolve_api_key(self) -> str:
        if self._explicit_api_key:
            return self._explicit_api_key
        env_val = os.getenv("TIINGO_API_KEY")
        if env_val:
            return env_val
        try:
            from shared.integration_keys import get_integration_key
            db_val = await get_integration_key("tiingo")
            if db_val:
                self._cached_api_key = db_val
                return db_val
        except Exception as e:
            logger.debug("Integration-keys DB lookup failed: %s", e)
        return ""

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the httpx client. Rebuilds when the API key rotates."""
        key = await self._resolve_api_key()
        if not key:
            logger.warning("TIINGO_API_KEY not configured (env var, factory, or admin UI) — requests will 401")
        if self._client is None or self._client_key != key:
            if self._client is not None:
                await self._client.aclose()
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Authorization": f"Token {key}"} if key else {},
            )
            self._client_key = key
        return self._client

    async def _close_client(self) -> None:
        """Close the httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _resolve_ticker(self, ticker: str) -> str | None:
        """Map ticker to Tiingo-compatible symbol.

        Returns:
            Mapped ticker, or None if unsupported (e.g., futures)
        """
        return _TIINGO_TICKER_MAP.get(ticker, ticker)

    async def _fetch_with_retry(
        self,
        url: str,
        params: dict | None = None,
    ) -> dict | list:
        """Fetch JSON from Tiingo with exponential backoff retry.

        Args:
            url: Full URL to fetch
            params: Query parameters

        Returns:
            Parsed JSON response (dict or list)

        Raises:
            httpx.HTTPError: If all retries fail
        """
        client = await self._get_client()
        last_error = None

        for attempt in range(self._max_retries):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.debug(
                        "Tiingo request failed (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        self._max_retries,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Tiingo request failed after %d attempts: %s",
                        self._max_retries,
                        e,
                    )

        raise last_error  # type: ignore

    def _parse_daily_response(self, data: list[dict]) -> pd.DataFrame:
        """Parse Tiingo daily API response into standard DataFrame.

        Args:
            data: List of price dicts from Tiingo

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date
        """
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame()

        # Tiingo daily response has: date, close, high, low, open, volume, adjClose, adjHigh, adjLow, adjOpen, adjVolume, divCash, splitFactor
        # Map to our standard schema
        df = df.rename(columns={
            "adjClose": "adj_close",
        })

        # Ensure required columns exist
        required = ["open", "high", "low", "close", "adj_close", "volume"]
        for col in required:
            if col not in df.columns:
                df[col] = 0.0

        df = df[["date"] + required]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.index.name = "date"

        return df

    def _parse_intraday_response(self, data: list[dict]) -> pd.DataFrame:
        """Parse Tiingo IEX intraday API response into standard DataFrame.

        Args:
            data: List of price dicts from Tiingo IEX endpoint

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date
        """
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame()

        # Tiingo IEX response has: date, open, high, low, close, volume
        # No adjusted prices for intraday - use close as adj_close
        if "adj_close" not in df.columns:
            df["adj_close"] = df["close"]

        required = ["open", "high", "low", "close", "adj_close", "volume"]
        for col in required:
            if col not in df.columns:
                df[col] = 0.0

        df = df[["date"] + required]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.index.name = "date"

        return df

    async def daily_bars(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars from Tiingo.

        Args:
            ticker: Stock symbol
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date. Empty DataFrame if ticker unsupported or error.
        """
        resolved = self._resolve_ticker(ticker)
        if resolved is None:
            logger.debug("Ticker %s not supported on Tiingo (futures)", ticker)
            return pd.DataFrame()

        url = f"{self._base_url}/tiingo/daily/{resolved}/prices"
        params = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "format": "json",
        }

        try:
            data = await self._fetch_with_retry(url, params)
            return self._parse_daily_response(data)
        except Exception as e:
            logger.error(
                "Failed to fetch daily bars for %s (resolved=%s): %s",
                ticker,
                resolved,
                e,
            )
            return pd.DataFrame()

    async def intraday_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        interval: str = "5m",
    ) -> pd.DataFrame:
        """Fetch intraday OHLCV bars from Tiingo IEX endpoint.

        Args:
            ticker: Stock symbol
            start: Start timestamp (inclusive)
            end: End timestamp (inclusive)
            interval: Bar interval (e.g., "5m", "15m", "1h")

        Returns:
            DataFrame with columns [open, high, low, close, adj_close, volume]
            indexed by date. Empty DataFrame if ticker unsupported or error.

        Note:
            Tiingo free tier IEX endpoint has ~30-day limit on intraday data.
        """
        resolved = self._resolve_ticker(ticker)
        if resolved is None:
            logger.debug("Ticker %s not supported on Tiingo (futures)", ticker)
            return pd.DataFrame()

        # Map interval to Tiingo resampleFreq
        freq_map = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1hour",
        }
        resample_freq = freq_map.get(interval, "5min")

        url = f"{self._base_url}/iex/{resolved}/prices"
        params = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "resampleFreq": resample_freq,
        }

        try:
            data = await self._fetch_with_retry(url, params)
            return self._parse_intraday_response(data)
        except Exception as e:
            logger.error(
                "Failed to fetch intraday bars for %s (resolved=%s): %s",
                ticker,
                resolved,
                e,
            )
            return pd.DataFrame()

    def supports_intraday(self) -> bool:
        """Return True - Tiingo supports intraday via IEX endpoint."""
        return True
