"""
Market data API routes (v1): live market data for dashboard widgets.

Uses yfinance for real-time data with aggressive in-memory caching (5-min TTL).
All endpoints gracefully degrade to sensible defaults when data is unavailable.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import yfinance as yf
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["market-data"])

# ---------------------------------------------------------------------------
# In-memory cache with 5-minute TTL
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # seconds


def _get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _set_cached(key: str, value: Any) -> Any:
    _cache[key] = (time.time(), value)
    return value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLC": "Communication",
    "XLY": "Consumer Disc.",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}

MAG7_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

POPULAR_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "AMD", "NFLX", "CRM", "AVGO", "ORCL", "ADBE", "INTC",
    "COST", "PEP", "CSCO", "QCOM", "TXN", "AMAT",
    "BA", "DIS", "JPM", "V", "MA", "UNH", "JNJ", "PG",
    "XOM", "CVX", "WMT", "HD", "MCD", "KO", "PFE",
    "COIN", "PLTR", "SOFI", "RIVN", "LCID", "NIO",
    "SQ", "SHOP", "SNAP", "ROKU", "UBER", "LYFT", "ABNB", "DKNG",
]

BOND_SYMBOLS: dict[str, str] = {
    "^IRX": "3M",
    "^FVX": "5Y",
    "^TNX": "10Y",
    "^TYX": "30Y",
}

BREADTH_INDICES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
}

CORRELATION_SYMBOLS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "USO", "UUP"]


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert a value to float safely, handling NaN and None."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _batch_download(tickers: list[str], period: str = "5d", interval: str = "1d") -> dict[str, Any]:
    """Download data for multiple tickers, returning per-ticker info dicts."""
    cache_key = f"batch_{'_'.join(sorted(tickers))}_{period}_{interval}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result: dict[str, Any] = {}
    try:
        df = yf.download(tickers, period=period, interval=interval, progress=False, threads=True)
        if df.empty:
            return _set_cached(cache_key, result)

        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    close_col = df["Close"]
                    volume_col = df["Volume"] if "Volume" in df.columns else None
                else:
                    close_col = df["Close"][ticker] if ticker in df["Close"].columns else None
                    has_vol = "Volume" in df.columns and ticker in df["Volume"].columns
                    volume_col = df["Volume"][ticker] if has_vol else None

                if close_col is None or close_col.dropna().empty:
                    continue

                closes = close_col.dropna()
                current = _safe_float(closes.iloc[-1])
                prev = _safe_float(closes.iloc[-2]) if len(closes) > 1 else current
                change = current - prev
                change_pct = (change / prev * 100) if prev != 0 else 0.0

                vol = 0
                avg_vol = 0
                if volume_col is not None:
                    vol_series = volume_col.dropna()
                    vol = int(_safe_float(vol_series.iloc[-1])) if len(vol_series) > 0 else 0
                    avg_vol = int(_safe_float(vol_series.mean())) if len(vol_series) > 0 else 0

                result[ticker] = {
                    "price": round(current, 2),
                    "prev_close": round(prev, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": vol,
                    "avg_volume": avg_vol,
                }
            except Exception as exc:
                logger.debug("Failed to parse ticker %s: %s", ticker, exc)
    except Exception as exc:
        logger.warning("yfinance batch download failed: %s", exc)

    return _set_cached(cache_key, result)


def _get_history(ticker: str, period: str = "1y") -> Any:
    """Get historical close prices for a ticker."""
    cache_key = f"hist_{ticker}_{period}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return None
        return _set_cached(cache_key, hist)
    except Exception as exc:
        logger.warning("yfinance history failed for %s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# 1. Top Movers
# ---------------------------------------------------------------------------
@router.get("/top-movers")
async def get_top_movers():
    """Top gainers and losers from a preset popular stock list."""
    cached = _get_cached("top_movers_result")
    if cached is not None:
        return cached

    data = _batch_download(POPULAR_TICKERS, period="2d", interval="1d")
    items = []
    for ticker, info in data.items():
        items.append({
            "ticker": ticker,
            "price": info["price"],
            "change_pct": info["change_pct"],
        })

    items.sort(key=lambda x: x["change_pct"], reverse=True)
    gainers = [i for i in items if i["change_pct"] > 0][:10]
    losers = sorted([i for i in items if i["change_pct"] < 0], key=lambda x: x["change_pct"])[:10]

    result = {"gainers": gainers, "losers": losers}
    return _set_cached("top_movers_result", result)


# ---------------------------------------------------------------------------
# 2. Sector Performance
# ---------------------------------------------------------------------------
@router.get("/sectors")
async def get_sector_performance():
    """Sector ETF performance (daily change)."""
    cached = _get_cached("sectors_result")
    if cached is not None:
        return cached

    tickers = list(SECTOR_ETFS.keys())
    data = _batch_download(tickers, period="2d", interval="1d")
    result = []
    for etf, sector in SECTOR_ETFS.items():
        info = data.get(etf)
        if info:
            result.append({
                "sector": sector,
                "etf": etf,
                "change_pct": info["change_pct"],
            })
    result.sort(key=lambda x: x["change_pct"], reverse=True)
    return _set_cached("sectors_result", result)


# ---------------------------------------------------------------------------
# 3. Fear & Greed
# ---------------------------------------------------------------------------
@router.get("/fear-greed")
async def get_fear_greed():
    """Fear & Greed approximation from VIX levels."""
    cached = _get_cached("fear_greed_result")
    if cached is not None:
        return cached

    try:
        hist = _get_history("^VIX", period="3mo")
        if hist is not None and len(hist) > 1:
            vix_current = _safe_float(hist["Close"].iloc[-1])
            vix_prev = _safe_float(hist["Close"].iloc[-2])
            vix_1w = _safe_float(hist["Close"].iloc[-5]) if len(hist) >= 5 else vix_current
            vix_1m = _safe_float(hist["Close"].iloc[-22]) if len(hist) >= 22 else vix_current

            # Map VIX to fear/greed score (inverted: low VIX = greed, high VIX = fear)
            def vix_to_score(v: float) -> float:
                return max(0, min(100, 100 - ((v - 10) / 30) * 100))

            score = vix_to_score(vix_current)
            prev_score = vix_to_score(vix_prev)
            score_1w = vix_to_score(vix_1w)
            score_1m = vix_to_score(vix_1m)

            if score <= 25:
                rating = "Extreme Fear"
            elif score <= 45:
                rating = "Fear"
            elif score <= 55:
                rating = "Neutral"
            elif score <= 75:
                rating = "Greed"
            else:
                rating = "Extreme Greed"

            result = {
                "score": round(score, 1),
                "rating": rating,
                "previous_close": round(prev_score, 1),
                "one_week_ago": round(score_1w, 1),
                "one_month_ago": round(score_1m, 1),
            }
            return _set_cached("fear_greed_result", result)
    except Exception as exc:
        logger.warning("Fear/Greed calculation failed: %s", exc)

    return {"score": 50, "rating": "Neutral", "previous_close": 50, "one_week_ago": 50, "one_month_ago": 50}


# ---------------------------------------------------------------------------
# 4. Bond Yields
# ---------------------------------------------------------------------------
@router.get("/bond-yields")
async def get_bond_yields():
    """Treasury yields from Yahoo Finance bond indices."""
    cached = _get_cached("bond_yields_result")
    if cached is not None:
        return cached

    tickers = list(BOND_SYMBOLS.keys())
    data = _batch_download(tickers, period="2d", interval="1d")
    result = []
    for sym, maturity in BOND_SYMBOLS.items():
        info = data.get(sym)
        if info:
            result.append({
                "maturity": maturity,
                "yield_pct": info["price"],
                "change": info["change"],
            })
    return _set_cached("bond_yields_result", result)


# ---------------------------------------------------------------------------
# 5. Market Breadth (major indices)
# ---------------------------------------------------------------------------
@router.get("/breadth")
async def get_market_breadth():
    """Major market indices with price and daily change."""
    cached = _get_cached("breadth_result")
    if cached is not None:
        return cached

    tickers = list(BREADTH_INDICES.keys())
    data = _batch_download(tickers, period="2d", interval="1d")
    result = []
    for sym, name in BREADTH_INDICES.items():
        info = data.get(sym)
        if info:
            result.append({
                "index": name,
                "price": info["price"],
                "change_pct": info["change_pct"],
            })
    return _set_cached("breadth_result", result)


# ---------------------------------------------------------------------------
# 6. Magnificent 7
# ---------------------------------------------------------------------------
@router.get("/mag7")
async def get_mag7():
    """Mag 7 stocks with price, change, and market cap."""
    cached = _get_cached("mag7_result")
    if cached is not None:
        return cached

    data = _batch_download(MAG7_TICKERS, period="2d", interval="1d")
    result = []
    for ticker in MAG7_TICKERS:
        info = data.get(ticker)
        if info:
            # Approximate market caps (updated periodically)
            try:
                t = yf.Ticker(ticker)
                mcap = _safe_float(t.info.get("marketCap", 0))
            except Exception:
                mcap = 0
            result.append({
                "ticker": ticker,
                "price": info["price"],
                "change_pct": info["change_pct"],
                "market_cap": mcap,
            })
    return _set_cached("mag7_result", result)


# ---------------------------------------------------------------------------
# 7. VIX Term Structure
# ---------------------------------------------------------------------------
@router.get("/vix-term-structure")
async def get_vix_term_structure():
    """VIX term structure from VIX futures proxies."""
    cached = _get_cached("vix_term_result")
    if cached is not None:
        return cached

    # VIX spot + VIX futures months (using VIX index as proxy)
    vix_tickers = ["^VIX", "^VIX9D"]  # 9-day VIX as additional data point
    data = _batch_download(vix_tickers, period="2d", interval="1d")

    vix_spot = data.get("^VIX", {})
    vix_9d = data.get("^VIX9D", {})

    spot_val = vix_spot.get("price", 15.0)
    spot_chg = vix_spot.get("change", 0.0)
    nine_d_val = vix_9d.get("price", spot_val - 0.5)
    nine_d_chg = vix_9d.get("change", 0.0)

    # Simulate a term structure (spot + projected months based on typical contango)
    points = [
        {"term": "9D", "value": round(nine_d_val, 2), "change": round(nine_d_chg, 2)},
        {"term": "Spot", "value": round(spot_val, 2), "change": round(spot_chg, 2)},
        {"term": "M1", "value": round(spot_val * 1.05, 2), "change": round(spot_chg * 0.8, 2)},
        {"term": "M2", "value": round(spot_val * 1.08, 2), "change": round(spot_chg * 0.6, 2)},
        {"term": "M3", "value": round(spot_val * 1.11, 2), "change": round(spot_chg * 0.4, 2)},
        {"term": "M4", "value": round(spot_val * 1.13, 2), "change": round(spot_chg * 0.3, 2)},
        {"term": "M5", "value": round(spot_val * 1.15, 2), "change": round(spot_chg * 0.2, 2)},
    ]

    is_backwardation = nine_d_val > spot_val * 1.05
    regime = "Backwardation (Fear)" if is_backwardation else "Contango (Normal)"

    result = {"points": points, "regime": regime}
    return _set_cached("vix_term_result", result)


# ---------------------------------------------------------------------------
# 8. SPX Key Levels
# ---------------------------------------------------------------------------
@router.get("/spx-levels")
async def get_spx_levels(symbol: str = Query("SPY")):
    """Key support/resistance levels for SPY or similar symbol."""
    cache_key = f"spx_levels_{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    hist = _get_history(symbol, period="3mo")
    if hist is None or hist.empty:
        return {}

    current = _safe_float(hist["Close"].iloc[-1])
    prev_high = _safe_float(hist["High"].iloc[-2]) if len(hist) > 1 else current
    prev_low = _safe_float(hist["Low"].iloc[-2]) if len(hist) > 1 else current
    prev_close = _safe_float(hist["Close"].iloc[-2]) if len(hist) > 1 else current

    # Classic pivot point calculation
    pivot = round((prev_high + prev_low + prev_close) / 3, 2)
    r1 = round(2 * pivot - prev_low, 2)
    r2 = round(pivot + (prev_high - prev_low), 2)
    s1 = round(2 * pivot - prev_high, 2)
    s2 = round(pivot - (prev_high - prev_low), 2)

    # Week high/low (last 5 trading days)
    week_data = hist.tail(5)
    week_high = round(_safe_float(week_data["High"].max()), 2)
    week_low = round(_safe_float(week_data["Low"].min()), 2)

    # Month high/low (last ~22 trading days)
    month_data = hist.tail(22)
    month_high = round(_safe_float(month_data["High"].max()), 2)
    month_low = round(_safe_float(month_data["Low"].min()), 2)

    # Approximate VWAP (Volume-Weighted Average Price for the day)
    if "Volume" in hist.columns:
        typical_price = (current + prev_high + prev_low) / 3
        vwap_approx = round(typical_price, 2)
    else:
        vwap_approx = round(current, 2)

    result = {
        "current": round(current, 2),
        "prev_high": round(prev_high, 2),
        "prev_low": round(prev_low, 2),
        "prev_close": round(prev_close, 2),
        "pivot": pivot,
        "r1": r1,
        "r2": r2,
        "s1": s1,
        "s2": s2,
        "week_high": week_high,
        "week_low": week_low,
        "month_high": month_high,
        "month_low": month_low,
        "vwap_approx": vwap_approx,
    }
    return _set_cached(cache_key, result)


# ---------------------------------------------------------------------------
# 9. Correlation Matrix
# ---------------------------------------------------------------------------
@router.get("/correlations")
async def get_correlations():
    """30-day rolling correlation matrix for key ETFs."""
    cached = _get_cached("correlations_result")
    if cached is not None:
        return cached

    try:
        df = yf.download(CORRELATION_SYMBOLS, period="2mo", interval="1d", progress=False, threads=True)
        if df.empty:
            return {"labels": [], "matrix": []}

        closes = df["Close"]
        returns = closes.pct_change().dropna().tail(30)

        if returns.empty or len(returns) < 10:
            return {"labels": [], "matrix": []}

        corr = returns.corr()
        labels = [str(c) for c in corr.columns.tolist()]
        matrix = []
        for i in range(len(labels)):
            row = []
            for j in range(len(labels)):
                row.append(round(_safe_float(corr.iloc[i, j]), 2))
            matrix.append(row)

        result = {"labels": labels, "matrix": matrix}
        return _set_cached("correlations_result", result)
    except Exception as exc:
        logger.warning("Correlation calculation failed: %s", exc)
        return {"labels": [], "matrix": []}


# ---------------------------------------------------------------------------
# 10. Premarket Gaps
# ---------------------------------------------------------------------------
@router.get("/premarket-gaps")
async def get_premarket_gaps():
    """Premarket gap up/down stocks. Uses previous close vs current price."""
    cached = _get_cached("premarket_gaps_result")
    if cached is not None:
        return cached

    data = _batch_download(POPULAR_TICKERS[:30], period="2d", interval="1d")
    gappers_up = []
    gappers_down = []

    for ticker, info in data.items():
        gap_pct = info["change_pct"]
        entry = {
            "ticker": ticker,
            "pre_price": info["price"],
            "prev_close": info["prev_close"],
            "gap_pct": gap_pct,
            "volume": info["volume"],
        }
        if gap_pct > 1.0:
            gappers_up.append(entry)
        elif gap_pct < -1.0:
            gappers_down.append(entry)

    gappers_up.sort(key=lambda x: x["gap_pct"], reverse=True)
    gappers_down.sort(key=lambda x: x["gap_pct"])

    result = {"gappers_up": gappers_up[:10], "gappers_down": gappers_down[:10]}
    return _set_cached("premarket_gaps_result", result)


# ---------------------------------------------------------------------------
# 11. Premarket Movers
# ---------------------------------------------------------------------------
@router.get("/premarket-movers")
async def get_premarket_movers():
    """Top premarket movers by absolute change percent."""
    cached = _get_cached("premarket_movers_result")
    if cached is not None:
        return cached

    data = _batch_download(POPULAR_TICKERS[:30], period="2d", interval="1d")
    items = []
    for ticker, info in data.items():
        items.append({
            "ticker": ticker,
            "pre_price": info["price"],
            "prev_close": info["prev_close"],
            "change_pct": info["change_pct"],
            "volume": info["volume"],
        })

    items.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return _set_cached("premarket_movers_result", items[:15])


# ---------------------------------------------------------------------------
# 12. Market Internals
# ---------------------------------------------------------------------------
@router.get("/internals")
async def get_market_internals():
    """Market internals: TICK, TRIN, ADD, VIX approximations."""
    cached = _get_cached("internals_result")
    if cached is not None:
        return cached

    vix_data = _batch_download(["^VIX"], period="2d", interval="1d")
    vix_info = vix_data.get("^VIX", {"price": 15.0, "change": 0.0})

    # Derive breadth info from index data
    idx_data = _batch_download(["^GSPC", "^DJI", "^IXIC"], period="2d", interval="1d")
    spx = idx_data.get("^GSPC", {"change_pct": 0.0})
    dji = idx_data.get("^DJI", {"change_pct": 0.0})
    ndx = idx_data.get("^IXIC", {"change_pct": 0.0})

    avg_chg = (spx.get("change_pct", 0) + dji.get("change_pct", 0) + ndx.get("change_pct", 0)) / 3

    # Simulate TICK based on market direction
    tick_val = round(avg_chg * 200, 2)
    tick_zone = "Bullish" if tick_val > 100 else "Bearish" if tick_val < -100 else "Neutral"

    # TRIN (Arms Index) simulation: < 1 bullish, > 1 bearish
    trin_val = round(max(0.3, 1.0 - avg_chg * 0.1), 2)
    trin_zone = "Bullish" if trin_val < 0.8 else "Bearish" if trin_val > 1.2 else "Neutral"

    # Advance-Decline
    add_val = round(avg_chg * 500, 2)
    add_zone = "Bullish" if add_val > 200 else "Bearish" if add_val < -200 else "Neutral"

    # VIX
    vix_val = vix_info.get("price", 15.0)
    vix_change = vix_info.get("change", 0.0)
    vix_zone = "Risk-Off" if vix_val > 20 else "Risk-On" if vix_val < 15 else "Neutral"

    result = [
        {"name": "TICK", "value": tick_val, "change": round(tick_val * 0.1, 2), "zone": tick_zone},
        {"name": "TRIN", "value": trin_val, "change": round(trin_val - 1.0, 2), "zone": trin_zone},
        {"name": "ADD", "value": add_val, "change": round(add_val * 0.05, 2), "zone": add_zone},
        {"name": "VIX", "value": round(vix_val, 2), "change": round(vix_change, 2), "zone": vix_zone},
    ]
    return _set_cached("internals_result", result)


# ---------------------------------------------------------------------------
# 13. Sector Rotation (multi-timeframe)
# ---------------------------------------------------------------------------
@router.get("/sector-rotation")
async def get_sector_rotation():
    """Sector ETF performance across 1W, 1M, 3M timeframes."""
    cached = _get_cached("sector_rotation_result")
    if cached is not None:
        return cached

    tickers = list(SECTOR_ETFS.keys())
    result = []

    try:
        df = yf.download(tickers, period="4mo", interval="1d", progress=False, threads=True)
        if df.empty:
            return []

        closes = df["Close"]
        for etf, sector in SECTOR_ETFS.items():
            try:
                col = closes[etf] if etf in closes.columns else None
                if col is None:
                    continue
                series = col.dropna()
                if len(series) < 2:
                    continue
                current = _safe_float(series.iloc[-1])
                w1 = _safe_float(series.iloc[-5]) if len(series) >= 5 else current
                m1 = _safe_float(series.iloc[-22]) if len(series) >= 22 else current
                m3 = _safe_float(series.iloc[-63]) if len(series) >= 63 else current

                result.append({
                    "sector": sector,
                    "etf": etf,
                    "1w": round((current - w1) / w1 * 100, 1) if w1 else 0,
                    "1m": round((current - m1) / m1 * 100, 1) if m1 else 0,
                    "3m": round((current - m3) / m3 * 100, 1) if m3 else 0,
                })
            except Exception:
                continue
    except Exception as exc:
        logger.warning("Sector rotation download failed: %s", exc)

    return _set_cached("sector_rotation_result", result)


# ---------------------------------------------------------------------------
# 14. 52-Week High/Low
# ---------------------------------------------------------------------------
@router.get("/52week")
async def get_52_week():
    """Stocks near 52-week highs and lows."""
    cached = _get_cached("52week_result")
    if cached is not None:
        return cached

    near_highs = []
    near_lows = []

    try:
        df = yf.download(POPULAR_TICKERS[:30], period="1y", interval="1d", progress=False, threads=True)
        if df.empty:
            return {"near_highs": [], "near_lows": []}

        closes = df["Close"]
        highs = df["High"]
        lows = df["Low"]

        for ticker in POPULAR_TICKERS[:30]:
            try:
                if ticker not in closes.columns:
                    continue
                c = closes[ticker].dropna()
                h = highs[ticker].dropna()
                lo = lows[ticker].dropna()

                if len(c) < 20:
                    continue

                current = _safe_float(c.iloc[-1])
                high_52w = _safe_float(h.max())
                low_52w = _safe_float(lo.min())

                if high_52w == 0 or low_52w == 0:
                    continue

                pct_from_high = round((current - high_52w) / high_52w * 100, 2)
                pct_from_low = round((current - low_52w) / low_52w * 100, 2)

                entry = {
                    "ticker": ticker,
                    "price": round(current, 2),
                    "high_52w": round(high_52w, 2),
                    "low_52w": round(low_52w, 2),
                    "pct_from_high": pct_from_high,
                    "pct_from_low": pct_from_low,
                }

                # Within 5% of 52w high
                if pct_from_high >= -5:
                    near_highs.append(entry)
                # Within 10% of 52w low
                if pct_from_low <= 10:
                    near_lows.append(entry)
            except Exception:
                continue
    except Exception as exc:
        logger.warning("52-week data download failed: %s", exc)

    near_highs.sort(key=lambda x: x["pct_from_high"], reverse=True)
    near_lows.sort(key=lambda x: x["pct_from_low"])

    result = {"near_highs": near_highs[:10], "near_lows": near_lows[:10]}
    return _set_cached("52week_result", result)


# ---------------------------------------------------------------------------
# 15. Put/Call Ratio
# ---------------------------------------------------------------------------
@router.get("/put-call-ratio")
async def get_put_call_ratio(symbols: str = Query("SPY")):
    """Put/call ratio for given symbols (options volume data)."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    cache_key = f"pcr_{'_'.join(sym_list)}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = []
    for sym in sym_list:
        try:
            t = yf.Ticker(sym)
            # Get the nearest expiration options chain
            expirations = t.options
            if not expirations:
                result.append({
                    "symbol": sym,
                    "put_volume": 0,
                    "call_volume": 0,
                    "ratio": 0.0,
                    "sentiment": "Neutral",
                })
                continue

            chain = t.option_chain(expirations[0])
            call_vol = int(_safe_float(chain.calls["volume"].sum()))
            put_vol = int(_safe_float(chain.puts["volume"].sum()))
            ratio = round(put_vol / call_vol, 3) if call_vol > 0 else 0.0

            if ratio > 1.0:
                sentiment = "Bearish"
            elif ratio < 0.7:
                sentiment = "Bullish"
            else:
                sentiment = "Neutral"

            result.append({
                "symbol": sym,
                "put_volume": put_vol,
                "call_volume": call_vol,
                "ratio": ratio,
                "sentiment": sentiment,
            })
        except Exception as exc:
            logger.debug("Put/call ratio failed for %s: %s", sym, exc)
            result.append({
                "symbol": sym,
                "put_volume": 0,
                "call_volume": 0,
                "ratio": 0.0,
                "sentiment": "Neutral",
            })

    return _set_cached(cache_key, result)


# ---------------------------------------------------------------------------
# 16. Relative Volume (RVOL)
# ---------------------------------------------------------------------------
@router.get("/rvol")
async def get_relative_volume():
    """Top stocks by relative volume vs 20-day average."""
    cached = _get_cached("rvol_result")
    if cached is not None:
        return cached

    tickers = POPULAR_TICKERS[:30]

    try:
        df = yf.download(tickers, period="1mo", interval="1d", progress=False, threads=True)
        if df.empty:
            return []

        items = []
        for ticker in tickers:
            try:
                if ticker not in df["Volume"].columns:
                    continue
                vol_series = df["Volume"][ticker].dropna()
                close_series = df["Close"][ticker].dropna()

                if len(vol_series) < 5:
                    continue

                current_vol = int(_safe_float(vol_series.iloc[-1]))
                avg_vol = int(_safe_float(vol_series.iloc[:-1].tail(20).mean()))
                current_price = _safe_float(close_series.iloc[-1])

                rvol = round(current_vol / avg_vol, 1) if avg_vol > 0 else 0.0

                items.append({
                    "ticker": ticker,
                    "volume": current_vol,
                    "avg_volume": avg_vol,
                    "rvol": rvol,
                    "price": round(current_price, 2),
                })
            except Exception:
                continue

        items.sort(key=lambda x: x["rvol"], reverse=True)
        return _set_cached("rvol_result", items[:15])
    except Exception as exc:
        logger.warning("RVOL download failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# 17. Gamma Exposure (GEX) — Approximation from options data
# ---------------------------------------------------------------------------
@router.get("/gex")
async def get_gamma_exposure(symbol: str = Query("SPY")):
    """Gamma exposure by strike (approximation from options chain)."""
    cache_key = f"gex_{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(symbol)
        spot = _safe_float(t.info.get("regularMarketPrice", 0))
        if spot == 0:
            hist = t.history(period="1d")
            spot = _safe_float(hist["Close"].iloc[-1]) if not hist.empty else 0

        expirations = t.options
        if not expirations or spot == 0:
            return {"symbol": symbol, "spot": spot, "total_gex": 0, "regime": "N/A", "flip_point": 0, "strikes": []}

        chain = t.option_chain(expirations[0])

        # Calculate GEX approximation per strike
        strikes_map: dict[float, float] = {}
        for _, row in chain.calls.iterrows():
            strike = _safe_float(row.get("strike", 0))
            oi = _safe_float(row.get("openInterest", 0))
            gamma = _safe_float(row.get("gamma", 0))
            gex = oi * gamma * 100 * spot
            if strike > 0:
                strikes_map[strike] = strikes_map.get(strike, 0) + gex

        for _, row in chain.puts.iterrows():
            strike = _safe_float(row.get("strike", 0))
            oi = _safe_float(row.get("openInterest", 0))
            gamma = _safe_float(row.get("gamma", 0))
            gex = -oi * gamma * 100 * spot  # puts have negative gamma effect
            if strike > 0:
                strikes_map[strike] = strikes_map.get(strike, 0) + gex

        # Filter to strikes near the money (within 10%)
        near_strikes = {
            k: v for k, v in strikes_map.items()
            if abs(k - spot) / spot <= 0.10
        }

        sorted_strikes = sorted(near_strikes.items(), key=lambda x: abs(x[1]), reverse=True)[:15]
        sorted_strikes.sort(key=lambda x: x[0])

        total_gex = sum(v for v in near_strikes.values())

        # Find flip point (where GEX changes sign)
        flip_point = spot
        sorted_all = sorted(near_strikes.items(), key=lambda x: x[0])
        for i in range(len(sorted_all) - 1):
            if sorted_all[i][1] * sorted_all[i + 1][1] < 0:
                flip_point = (sorted_all[i][0] + sorted_all[i + 1][0]) / 2
                break

        regime = "Long Gamma (Pinning)" if total_gex > 0 else "Short Gamma (Volatile)"

        result = {
            "symbol": symbol,
            "spot": round(spot, 2),
            "total_gex": round(total_gex, 0),
            "regime": regime,
            "flip_point": round(flip_point, 2),
            "strikes": [
                {"strike": round(s, 2), "gex": round(g, 0)}
                for s, g in sorted_strikes
            ],
        }
        return _set_cached(cache_key, result)
    except Exception as exc:
        logger.warning("GEX calculation failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "spot": 0, "total_gex": 0, "regime": "N/A", "flip_point": 0, "strikes": []}


# ---------------------------------------------------------------------------
# 18. Options Flow
# ---------------------------------------------------------------------------
@router.get("/options-flow")
async def get_options_flow(symbols: str = Query("SPY")):
    """Options flow data with unusual activity detection."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    cache_key = f"flow_{'_'.join(sym_list)}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = []
    for sym in sym_list:
        try:
            t = yf.Ticker(sym)
            expirations = t.options
            if not expirations:
                result.append({
                    "symbol": sym, "call_volume": 0, "put_volume": 0,
                    "call_oi": 0, "put_oi": 0, "pc_ratio": 0.0, "unusual_activity": [],
                })
                continue

            chain = t.option_chain(expirations[0])
            call_vol = int(_safe_float(chain.calls["volume"].sum()))
            put_vol = int(_safe_float(chain.puts["volume"].sum()))
            call_oi = int(_safe_float(chain.calls["openInterest"].sum()))
            put_oi = int(_safe_float(chain.puts["openInterest"].sum()))
            pc_ratio = round(put_vol / call_vol, 3) if call_vol > 0 else 0.0

            # Detect unusual activity (volume >> open interest)
            unusual = []
            for _, row in chain.calls.iterrows():
                vol = _safe_float(row.get("volume", 0))
                oi = _safe_float(row.get("openInterest", 0))
                if oi > 0 and vol > 0 and vol / oi > 3:
                    unusual.append({
                        "strike": round(_safe_float(row.get("strike", 0)), 2),
                        "type": "CALL",
                        "volume": int(vol),
                        "oi": int(oi),
                        "ratio": round(vol / oi, 1),
                        "exp": expirations[0],
                    })
            for _, row in chain.puts.iterrows():
                vol = _safe_float(row.get("volume", 0))
                oi = _safe_float(row.get("openInterest", 0))
                if oi > 0 and vol > 0 and vol / oi > 3:
                    unusual.append({
                        "strike": round(_safe_float(row.get("strike", 0)), 2),
                        "type": "PUT",
                        "volume": int(vol),
                        "oi": int(oi),
                        "ratio": round(vol / oi, 1),
                        "exp": expirations[0],
                    })

            unusual.sort(key=lambda x: x["ratio"], reverse=True)

            result.append({
                "symbol": sym,
                "call_volume": call_vol,
                "put_volume": put_vol,
                "call_oi": call_oi,
                "put_oi": put_oi,
                "pc_ratio": pc_ratio,
                "unusual_activity": unusual[:10],
            })
        except Exception as exc:
            logger.debug("Options flow failed for %s: %s", sym, exc)
            result.append({
                "symbol": sym, "call_volume": 0, "put_volume": 0,
                "call_oi": 0, "put_oi": 0, "pc_ratio": 0.0, "unusual_activity": [],
            })

    return _set_cached(cache_key, result)


# ---------------------------------------------------------------------------
# 19. Volatility Dashboard
# ---------------------------------------------------------------------------
@router.get("/volatility")
async def get_volatility(symbol: str = Query("SPY")):
    """IV, HV, and volatility metrics for a symbol."""
    cache_key = f"vol_{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        hist = _get_history(symbol, period="1y")
        if hist is None or hist.empty or len(hist) < 30:
            return _default_volatility()

        closes = hist["Close"].dropna()
        returns = closes.pct_change().dropna()

        # Historical volatilities (annualized)
        hv_10 = round(float(returns.tail(10).std() * np.sqrt(252) * 100), 1)
        hv_20 = round(float(returns.tail(20).std() * np.sqrt(252) * 100), 1)
        hv_30 = round(float(returns.tail(30).std() * np.sqrt(252) * 100), 1)

        # Implied volatility approximation from options
        iv_current = hv_20  # Default to HV if no IV available
        try:
            t = yf.Ticker(symbol)
            exps = t.options
            if exps:
                chain = t.option_chain(exps[0])
                atm_calls = chain.calls
                spot = _safe_float(closes.iloc[-1])
                # Find ATM options
                if len(atm_calls) > 0 and "impliedVolatility" in atm_calls.columns:
                    atm_calls = atm_calls.copy()
                    atm_calls["dist"] = abs(atm_calls["strike"] - spot)
                    nearest = atm_calls.nsmallest(3, "dist")
                    iv_vals = nearest["impliedVolatility"].dropna()
                    if len(iv_vals) > 0:
                        iv_current = round(float(iv_vals.mean() * 100), 1)
        except Exception:
            pass

        # IV rank and percentile (using HV as proxy for historical IV range)
        all_hv = [float(returns.iloc[max(0, i - 20):i].std() * np.sqrt(252) * 100) for i in range(20, len(returns))]
        if all_hv:
            iv_high_52w = round(max(all_hv), 1)
            iv_low_52w = round(min(all_hv), 1)
            iv_range = iv_high_52w - iv_low_52w
            iv_rank = round((iv_current - iv_low_52w) / iv_range * 100, 0) if iv_range > 0 else 50
            iv_percentile = round(sum(1 for v in all_hv if v <= iv_current) / len(all_hv) * 100, 0)
        else:
            iv_high_52w = iv_current + 10
            iv_low_52w = max(iv_current - 10, 5)
            iv_rank = 50.0
            iv_percentile = 50.0

        hv_iv_spread = round(hv_20 - iv_current, 1)

        result = {
            "iv_current": iv_current,
            "iv_rank": iv_rank,
            "iv_percentile": iv_percentile,
            "iv_high_52w": iv_high_52w,
            "iv_low_52w": iv_low_52w,
            "hv_10": hv_10,
            "hv_20": hv_20,
            "hv_30": hv_30,
            "hv_iv_spread": hv_iv_spread,
        }
        return _set_cached(cache_key, result)
    except Exception as exc:
        logger.warning("Volatility calculation failed for %s: %s", symbol, exc)
        return _default_volatility()


def _default_volatility() -> dict:
    return {
        "iv_current": 0, "iv_rank": 0, "iv_percentile": 0,
        "iv_high_52w": 0, "iv_low_52w": 0,
        "hv_10": 0, "hv_20": 0, "hv_30": 0, "hv_iv_spread": 0,
    }


# ---------------------------------------------------------------------------
# 20. Day Trade P&L (from Phoenix DB or defaults)
# ---------------------------------------------------------------------------
@router.get("/day-pnl")
async def get_day_pnl():
    """Today's day-trading P&L summary. Returns live data from DB if available."""
    cached = _get_cached("day_pnl_result")
    if cached is not None:
        return cached

    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Try loading from the database
    try:
        from sqlalchemy import func, select

        from shared.db.engine import async_session_factory
        from shared.db.models import Trade

        async with async_session_factory() as session:
            stmt = select(Trade).where(
                func.date(Trade.executed_at) == today,
                Trade.pnl.isnot(None),
            ).order_by(Trade.executed_at.desc())
            rows = (await session.execute(stmt)).scalars().all()

            if rows:
                trades_list = []
                total_pnl = 0.0
                wins = 0
                losses = 0
                win_pnls = []
                loss_pnls = []

                for t in rows:
                    pnl_val = _safe_float(t.pnl)
                    total_pnl += pnl_val
                    if pnl_val >= 0:
                        wins += 1
                        win_pnls.append(pnl_val)
                    else:
                        losses += 1
                        loss_pnls.append(pnl_val)
                    trades_list.append({
                        "ticker": t.symbol or "???",
                        "side": t.side or "BUY",
                        "pnl": round(pnl_val, 2),
                        "time": t.executed_at.strftime("%H:%M") if t.executed_at else "",
                    })

                trade_count = wins + losses
                result = {
                    "date": today,
                    "total_pnl": round(total_pnl, 2),
                    "trade_count": trade_count,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(wins / trade_count * 100, 0) if trade_count > 0 else 0,
                    "avg_win": round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0,
                    "avg_loss": round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0,
                    "trades": trades_list[:20],
                }
                return _set_cached("day_pnl_result", result)
    except Exception as exc:
        logger.debug("DB trade query failed (expected in dev): %s", exc)

    # Fallback: empty day
    result = {
        "date": today,
        "total_pnl": 0.0,
        "trade_count": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0,
        "avg_win": 0,
        "avg_loss": 0,
        "trades": [],
    }
    return _set_cached("day_pnl_result", result)


# ---------------------------------------------------------------------------
# 21. IPO Calendar (recent IPOs from popular universe)
# ---------------------------------------------------------------------------
@router.get("/ipo-calendar")
async def get_ipo_calendar():
    """Recent IPO/newly listed stocks performance."""
    cached = _get_cached("ipo_calendar_result")
    if cached is not None:
        return cached

    # Recent notable IPOs/DPOs (manually curated, updated periodically)
    ipo_tickers = ["ARM", "BIRK", "CART", "TOST", "RIVN", "LCID", "COIN", "PLTR", "SNOW", "ABNB"]

    data = _batch_download(ipo_tickers, period="2d", interval="1d")
    result = []
    for ticker in ipo_tickers:
        info = data.get(ticker)
        if info:
            # Get market cap
            mcap = 0
            try:
                t = yf.Ticker(ticker)
                mcap = _safe_float(t.info.get("marketCap", 0))
            except Exception:
                pass
            result.append({
                "ticker": ticker,
                "price": info["price"],
                "change_pct": info["change_pct"],
                "market_cap": mcap,
            })

    return _set_cached("ipo_calendar_result", result)
