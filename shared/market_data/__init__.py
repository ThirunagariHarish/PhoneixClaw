"""Market data provider abstraction.

Provides a clean interface for fetching OHLCV data from multiple providers
(Tiingo, yfinance) with automatic failover and standardized DataFrame schema.
"""

from __future__ import annotations

from .base import MarketDataProvider
from .factory import get_provider
from .tiingo import TiingoProvider
from .yfinance_fallback import YFinanceProvider

__all__ = [
    "MarketDataProvider",
    "TiingoProvider",
    "YFinanceProvider",
    "get_provider",
]
