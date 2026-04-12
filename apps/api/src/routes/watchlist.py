"""
Watchlist API routes: real-time-ish quotes for given symbols via yfinance,
plus server-side persistence of watchlist items per user.

Caches results for 60 seconds to avoid rate limits.
"""

import logging
import time as _time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select

from apps.api.src.deps import DbSession
from shared.db.models.watchlist_item import WatchlistItem

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

        quote: dict[str, Any] = {
            "symbol": symbol.upper(),
            "price": round(price, 2),
            "change": change,
            "change_pct": change_pct,
            "volume": volume,
            "market_cap": market_cap,
            "fifty_two_week_high": year_high,
            "fifty_two_week_low": year_low,
        }

        # Fundamentals (P/E, EPS, dividend yield, next earnings date)
        try:
            full_info = ticker.info or {}
            quote["pe_ratio"] = full_info.get("trailingPE")
            quote["eps"] = full_info.get("trailingEps")
            quote["dividend_yield"] = full_info.get("dividendYield")
            # Next earnings date from calendar
            try:
                cal = ticker.calendar
                if cal is not None and hasattr(cal, "get"):
                    earnings_date = cal.get("Earnings Date")
                    if earnings_date and len(earnings_date) > 0:
                        quote["next_earnings"] = str(earnings_date[0])
                elif cal is not None and hasattr(cal, "iloc"):
                    # pandas DataFrame format
                    quote["next_earnings"] = str(cal.iloc[0, 0]) if len(cal) > 0 else None
                else:
                    quote["next_earnings"] = None
            except Exception:
                quote["next_earnings"] = None
        except Exception:
            quote["pe_ratio"] = None
            quote["eps"] = None
            quote["dividend_yield"] = None
            quote["next_earnings"] = None

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
            "pe_ratio": None,
            "eps": None,
            "dividend_yield": None,
            "next_earnings": None,
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


# ---------------------------------------------------------------------------
# Server-side watchlist persistence
# ---------------------------------------------------------------------------

# Placeholder user_id for when auth is not enforced.
_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class WatchlistAddRequest(BaseModel):
    symbols: list[str]
    watchlist_name: str = "Default"


class WatchlistRenameRequest(BaseModel):
    old_name: str
    new_name: str


class WatchlistDeleteRequest(BaseModel):
    watchlist_name: str


@router.get("/lists")
async def get_watchlists(session: DbSession):
    """Return all watchlist names and their tickers for the current user."""
    result = await session.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == _DEFAULT_USER_ID)
        .order_by(WatchlistItem.watchlist_name, WatchlistItem.added_at)
    )
    items = result.scalars().all()
    lists: dict[str, list[str]] = {}
    for item in items:
        lists.setdefault(item.watchlist_name, []).append(item.symbol)
    return {"watchlists": lists}


@router.post("/lists")
async def add_to_watchlist(payload: WatchlistAddRequest, session: DbSession):
    """Add symbols to a named watchlist. Creates the watchlist if it does not exist."""
    added = []
    for sym in payload.symbols:
        sym_upper = sym.strip().upper()
        if not sym_upper:
            continue
        # Check if already exists
        existing = await session.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == _DEFAULT_USER_ID,
                WatchlistItem.watchlist_name == payload.watchlist_name,
                WatchlistItem.symbol == sym_upper,
            )
        )
        if existing.scalar_one_or_none():
            continue
        item = WatchlistItem(
            user_id=_DEFAULT_USER_ID,
            watchlist_name=payload.watchlist_name,
            symbol=sym_upper,
        )
        session.add(item)
        added.append(sym_upper)
    await session.commit()
    return {"added": added, "watchlist_name": payload.watchlist_name}


@router.delete("/lists/{watchlist_name}/symbols/{symbol}")
async def remove_from_watchlist(watchlist_name: str, symbol: str, session: DbSession):
    """Remove a single symbol from a named watchlist."""
    await session.execute(
        delete(WatchlistItem).where(
            WatchlistItem.user_id == _DEFAULT_USER_ID,
            WatchlistItem.watchlist_name == watchlist_name,
            WatchlistItem.symbol == symbol.upper(),
        )
    )
    await session.commit()
    return {"removed": symbol.upper(), "watchlist_name": watchlist_name}


@router.post("/lists/rename")
async def rename_watchlist(payload: WatchlistRenameRequest, session: DbSession):
    """Rename a watchlist."""
    result = await session.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == _DEFAULT_USER_ID,
            WatchlistItem.watchlist_name == payload.old_name,
        )
    )
    items = result.scalars().all()
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    for item in items:
        item.watchlist_name = payload.new_name
    await session.commit()
    return {"old_name": payload.old_name, "new_name": payload.new_name}


@router.delete("/lists/{watchlist_name}")
async def delete_watchlist(watchlist_name: str, session: DbSession):
    """Delete an entire named watchlist."""
    await session.execute(
        delete(WatchlistItem).where(
            WatchlistItem.user_id == _DEFAULT_USER_ID,
            WatchlistItem.watchlist_name == watchlist_name,
        )
    )
    await session.commit()
    return {"deleted": watchlist_name}
