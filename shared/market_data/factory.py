"""Factory for creating market data providers.

Selects provider based on environment variables:
- PHOENIX_MARKET_DATA_PROVIDER: explicit provider name ("tiingo" or "yfinance")
- TIINGO_API_KEY: if set, defaults to Tiingo, otherwise yfinance
"""

from __future__ import annotations

import logging
import os

from .base import MarketDataProvider
from .tiingo import TiingoProvider
from .yfinance_fallback import YFinanceProvider

logger = logging.getLogger(__name__)

# Module-level cache for singleton provider instance
_provider_instance: MarketDataProvider | None = None


def get_provider(name: str | None = None) -> MarketDataProvider:
    """Get market data provider instance.

    Args:
        name: Explicit provider name ("tiingo" or "yfinance").
              If None, selects based on environment variables.

    Returns:
        MarketDataProvider instance (cached for process lifetime)

    Selection logic:
        1. If name is provided, use that provider
        2. If PHOENIX_MARKET_DATA_PROVIDER env var is set, use that
        3. If TIINGO_API_KEY is set, use Tiingo
        4. Otherwise, use yfinance
    """
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    # Determine provider name
    if name is None:
        name = os.getenv("PHOENIX_MARKET_DATA_PROVIDER", "").lower()

    if not name:
        # Auto-detect based on API key availability
        if os.getenv("TIINGO_API_KEY"):
            name = "tiingo"
        else:
            name = "yfinance"

    # Create provider instance
    if name == "tiingo":
        logger.info("Using Tiingo market data provider")
        _provider_instance = TiingoProvider()
    elif name == "yfinance":
        logger.info("Using yfinance market data provider")
        _provider_instance = YFinanceProvider()
    else:
        raise ValueError(
            f"Unknown market data provider: {name}. Must be 'tiingo' or 'yfinance'"
        )

    return _provider_instance
