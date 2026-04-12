"""
Watchlist API routes: real-time-ish quotes for given symbols via yfinance.

Caches results for 60 seconds to avoid rate limits.
"""

import logging
import time as _time
from typing import Any

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/watchlist", tags=["watchlist"])

# Simple in-memory cache: key -> (timestamp, data)
_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 60  # seconds


def _fetch_quote(symbol: str) -> dict[str, Any]:
    """Fetch a single symbol quote via yfinance with caching."""
    now = _time.time()
    cached = _quote_cache.get(symbol)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = float(info.last_price) if hasattr(info, "last_price") and info.last_price else 0.0
        prev_close = float(info.previous_close) if hasattr(info, "previous_close") and info.previous_close else 0.0
        change = round(price - prev_close, 2) if prev_close else 0.0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
        market_cap = float(info.market_cap) if hasattr(info, "market_cap") and info.market_cap else None
        volume = int(info.last_volume) if hasattr(info, "last_volume") and info.last_volume else 0

        # 52-week high/low
        year_high = float(info.year_high) if hasattr(info, "year_high") and info.year_high else None
        year_low = float(info.year_low) if hasattr(info, "year_low") and info.year_low else None

        quote = {
            "symbol": symbol.upper(),
            "price": round(price, 2),
            "change": change,
            "change_pct": change_pct,
            "volume": volume,
            "market_cap": market_cap,
            "fifty_two_week_high": year_high,
            "fifty_two_week_low": year_low,
        }
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
        quote = {
            "symbol": symbol.upper(),
            "price": 0,
            "change": 0,
            "change_pct": 0,
            "volume": 0,
            "market_cap": None,
            "fifty_two_week_high": None,
            "fifty_two_week_low": None,
        }

    _quote_cache[symbol] = (now, quote)
    return quote


@router.get("/quotes")
async def get_watchlist_quotes(
    symbols: str = Query("SPY", description="Comma-separated list of ticker symbols"),
) -> list[dict[str, Any]]:
    """Return real-time-ish quotes for given symbols. Cached 60s."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return []
    # Cap at 20 symbols per request
    symbol_list = symbol_list[:20]
    return [_fetch_quote(sym) for sym in symbol_list]
