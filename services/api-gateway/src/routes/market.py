"""
Market data endpoints for the Global Market Command Center.

All yfinance calls run via asyncio.to_thread with in-memory TTL caching
to avoid rate-limiting and keep response times low.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/market", tags=["market"])

_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 300  # 5 minutes


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    return None


def _set_cached(key: str, data: object):
    _cache[key] = (time.time(), data)


# ── Fear & Greed ──────────────────────────────────────────────────────────────

@router.get("/fear-greed")
async def fear_greed():
    cached = _get_cached("fear-greed")
    if cached:
        return cached

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
            if resp.status_code == 200:
                data = resp.json()
                fg = data.get("fear_and_greed", {})
                result = {
                    "score": fg.get("score", 50),
                    "rating": fg.get("rating", "Neutral"),
                    "previous_close": fg.get("previous_close", 50),
                    "one_week_ago": fg.get("previous_1_week", 50),
                    "one_month_ago": fg.get("previous_1_month", 50),
                    "one_year_ago": fg.get("previous_1_year", 50),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                _set_cached("fear-greed", result)
                return result
    except Exception as e:
        logger.warning("Fear & Greed fetch failed: %s", e)

    fallback = {"score": 50, "rating": "Neutral", "timestamp": datetime.utcnow().isoformat(), "source": "fallback"}
    return fallback


# ── Mag 7 ─────────────────────────────────────────────────────────────────────

MAG7_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

@router.get("/mag7")
async def mag7():
    cached = _get_cached("mag7")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        data = []
        for ticker in MAG7_TICKERS:
            try:
                t = yf.Ticker(ticker)
                info = t.fast_info
                hist = t.history(period="2d")
                if len(hist) >= 2:
                    prev = hist["Close"].iloc[-2]
                    curr = hist["Close"].iloc[-1]
                    change_pct = ((curr - prev) / prev) * 100
                else:
                    curr = getattr(info, "last_price", 0) or 0
                    change_pct = 0
                data.append({
                    "ticker": ticker,
                    "price": round(float(curr), 2),
                    "change_pct": round(float(change_pct), 2),
                    "market_cap": getattr(info, "market_cap", 0) or 0,
                })
            except Exception:
                data.append({"ticker": ticker, "price": 0, "change_pct": 0, "market_cap": 0})
        return data

    result = await asyncio.to_thread(_fetch)
    _set_cached("mag7", result)
    return result


# ── Sector Performance ────────────────────────────────────────────────────────

SECTOR_ETFS = {
    "Technology": "XLK", "Financials": "XLF", "Healthcare": "XLV",
    "Energy": "XLE", "Consumer Disc.": "XLY", "Consumer Staples": "XLP",
    "Industrials": "XLI", "Materials": "XLB", "Real Estate": "XLRE",
    "Utilities": "XLU", "Communication": "XLC",
}

@router.get("/sectors")
async def sectors():
    cached = _get_cached("sectors")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        data = []
        for name, etf in SECTOR_ETFS.items():
            try:
                hist = yf.Ticker(etf).history(period="2d")
                if len(hist) >= 2:
                    prev = hist["Close"].iloc[-2]
                    curr = hist["Close"].iloc[-1]
                    change_pct = ((curr - prev) / prev) * 100
                else:
                    curr, change_pct = 0, 0
                data.append({"sector": name, "etf": etf, "price": round(float(curr), 2), "change_pct": round(float(change_pct), 2)})
            except Exception:
                data.append({"sector": name, "etf": etf, "price": 0, "change_pct": 0})
        data.sort(key=lambda x: x["change_pct"], reverse=True)
        return data

    result = await asyncio.to_thread(_fetch)
    _set_cached("sectors", result)
    return result


# ── Top Movers ────────────────────────────────────────────────────────────────

@router.get("/top-movers")
async def top_movers():
    cached = _get_cached("top-movers")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        watchlist = [
            "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "NFLX", "CRM", "COIN", "PLTR", "SOFI", "NIO", "RIVN", "BABA",
            "DIS", "JPM", "BA", "PYPL", "SQ", "ROKU", "SNAP",
        ]
        results = []
        for ticker in watchlist:
            try:
                hist = yf.Ticker(ticker).history(period="2d")
                if len(hist) >= 2:
                    prev = hist["Close"].iloc[-2]
                    curr = hist["Close"].iloc[-1]
                    change_pct = ((curr - prev) / prev) * 100
                    results.append({"ticker": ticker, "price": round(float(curr), 2), "change_pct": round(float(change_pct), 2)})
            except Exception:
                pass
        results.sort(key=lambda x: x["change_pct"], reverse=True)
        return {"gainers": results[:5], "losers": results[-5:][::-1]}

    result = await asyncio.to_thread(_fetch)
    _set_cached("top-movers", result)
    return result


# ── Bond Yields ───────────────────────────────────────────────────────────────

BOND_TICKERS = {"2Y": "^IRX", "5Y": "^FVX", "10Y": "^TNX", "30Y": "^TYX"}

@router.get("/bond-yields")
async def bond_yields():
    cached = _get_cached("bond-yields")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        data = []
        for label, ticker in BOND_TICKERS.items():
            try:
                hist = yf.Ticker(ticker).history(period="5d")
                if not hist.empty:
                    curr = hist["Close"].iloc[-1]
                    prev = hist["Close"].iloc[-2] if len(hist) >= 2 else curr
                    data.append({
                        "maturity": label,
                        "yield_pct": round(float(curr), 3),
                        "change": round(float(curr - prev), 3),
                    })
            except Exception:
                data.append({"maturity": label, "yield_pct": 0, "change": 0})
        return data

    result = await asyncio.to_thread(_fetch)
    _set_cached("bond-yields", result)
    return result


# ── Market Breadth ────────────────────────────────────────────────────────────

@router.get("/breadth")
async def market_breadth():
    cached = _get_cached("breadth")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        indices = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Dow Jones": "^DJI", "Russell 2000": "^RUT"}
        data = []
        for name, ticker in indices.items():
            try:
                hist = yf.Ticker(ticker).history(period="2d")
                if len(hist) >= 2:
                    prev = hist["Close"].iloc[-2]
                    curr = hist["Close"].iloc[-1]
                    change_pct = ((curr - prev) / prev) * 100
                    data.append({
                        "index": name, "ticker": ticker,
                        "price": round(float(curr), 2),
                        "change_pct": round(float(change_pct), 2),
                    })
            except Exception:
                data.append({"index": name, "ticker": ticker, "price": 0, "change_pct": 0})
        return data

    result = await asyncio.to_thread(_fetch)
    _set_cached("breadth", result)
    return result


# ── Put/Call Ratio ───────────────────────────────────────────────────────────

@router.get("/put-call-ratio")
async def put_call_ratio():
    cached = _get_cached("put-call-ratio")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        symbols = ["SPY", "QQQ"]
        results = []
        for sym in symbols:
            try:
                t = yf.Ticker(sym)
                dates = t.options[:3] if len(t.options) >= 3 else t.options
                total_put_vol = 0
                total_call_vol = 0
                for exp in dates:
                    chain = t.option_chain(exp)
                    total_put_vol += int(chain.puts["volume"].sum()) if "volume" in chain.puts.columns else 0
                    total_call_vol += int(chain.calls["volume"].sum()) if "volume" in chain.calls.columns else 0
                ratio = round(total_put_vol / max(total_call_vol, 1), 3)
                sentiment = "Bearish" if ratio > 1.0 else "Bullish" if ratio < 0.7 else "Neutral"
                results.append({
                    "symbol": sym,
                    "put_volume": total_put_vol,
                    "call_volume": total_call_vol,
                    "ratio": ratio,
                    "sentiment": sentiment,
                })
            except Exception as e:
                logger.warning("Put/Call ratio fetch failed for %s: %s", sym, e)
                results.append({"symbol": sym, "put_volume": 0, "call_volume": 0, "ratio": 0, "sentiment": "N/A"})
        return results

    result = await asyncio.to_thread(_fetch)
    _set_cached("put-call-ratio", result)
    return result


# ── IPO Calendar ─────────────────────────────────────────────────────────────

@router.get("/ipo-calendar")
async def ipo_calendar():
    cached = _get_cached("ipo-calendar")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        recent_ipos = [
            "ARM", "CART", "BIRK", "KVYO", "VFS",
            "ONON", "DUOL", "RDDT", "IBKR",
        ]
        results = []
        for ticker in recent_ipos:
            try:
                t = yf.Ticker(ticker)
                info = t.fast_info
                hist = t.history(period="5d")
                if not hist.empty:
                    curr = round(float(hist["Close"].iloc[-1]), 2)
                    prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else curr
                    change_pct = round(((curr - prev) / prev) * 100, 2) if prev else 0
                else:
                    curr, change_pct = 0, 0
                results.append({
                    "ticker": ticker,
                    "price": curr,
                    "change_pct": change_pct,
                    "market_cap": getattr(info, "market_cap", 0) or 0,
                })
            except Exception:
                results.append({"ticker": ticker, "price": 0, "change_pct": 0, "market_cap": 0})
        return results

    result = await asyncio.to_thread(_fetch)
    _set_cached("ipo-calendar", result)
    return result


# ── Relative Volume (RVOL) ──────────────────────────────────────────────────

@router.get("/rvol")
async def relative_volume():
    cached = _get_cached("rvol")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "NFLX", "CRM", "COIN", "PLTR", "SOFI", "BA", "DIS",
            "JPM", "PYPL", "SQ", "ROKU", "SNAP",
        ]
        results = []
        for ticker in watchlist:
            try:
                hist = yf.Ticker(ticker).history(period="1mo")
                if len(hist) >= 5:
                    today_vol = float(hist["Volume"].iloc[-1])
                    avg_vol = float(hist["Volume"].iloc[-21:-1].mean()) if len(hist) >= 21 else float(hist["Volume"].iloc[:-1].mean())
                    rvol = round(today_vol / max(avg_vol, 1), 2)
                    results.append({
                        "ticker": ticker,
                        "volume": int(today_vol),
                        "avg_volume": int(avg_vol),
                        "rvol": rvol,
                        "price": round(float(hist["Close"].iloc[-1]), 2),
                    })
            except Exception:
                pass
        results.sort(key=lambda x: x["rvol"], reverse=True)
        return results[:15]

    result = await asyncio.to_thread(_fetch)
    _set_cached("rvol", result)
    return result


# ── 52-Week Highs/Lows ──────────────────────────────────────────────────────

@router.get("/52week")
async def fifty_two_week():
    cached = _get_cached("52week")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "NFLX", "CRM", "COIN", "PLTR", "SOFI", "BA", "DIS",
            "JPM", "GS", "WMT", "COST", "V", "MA", "UNH", "HD", "PG",
        ]
        highs = []
        lows = []
        for ticker in watchlist:
            try:
                hist = yf.Ticker(ticker).history(period="1y")
                if len(hist) < 20:
                    continue
                curr = float(hist["Close"].iloc[-1])
                high_52 = float(hist["High"].max())
                low_52 = float(hist["Low"].min())
                pct_from_high = round(((curr - high_52) / high_52) * 100, 2)
                pct_from_low = round(((curr - low_52) / low_52) * 100, 2)
                entry = {
                    "ticker": ticker,
                    "price": round(curr, 2),
                    "high_52w": round(high_52, 2),
                    "low_52w": round(low_52, 2),
                    "pct_from_high": pct_from_high,
                    "pct_from_low": pct_from_low,
                }
                if pct_from_high >= -5:
                    highs.append(entry)
                if pct_from_low <= 10:
                    lows.append(entry)
            except Exception:
                pass
        highs.sort(key=lambda x: x["pct_from_high"], reverse=True)
        lows.sort(key=lambda x: x["pct_from_low"])
        return {"near_highs": highs[:10], "near_lows": lows[:10]}

    result = await asyncio.to_thread(_fetch)
    _set_cached("52week", result)
    return result


# ── Sector Rotation (multi-timeframe) ───────────────────────────────────────

@router.get("/sector-rotation")
async def sector_rotation():
    cached = _get_cached("sector-rotation")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        etfs = {
            "Technology": "XLK", "Financials": "XLF", "Healthcare": "XLV",
            "Energy": "XLE", "Consumer Disc.": "XLY", "Consumer Staples": "XLP",
            "Industrials": "XLI", "Materials": "XLB", "Real Estate": "XLRE",
            "Utilities": "XLU", "Communication": "XLC",
        }
        periods = {"1w": "5d", "1m": "1mo", "3m": "3mo"}
        results = []
        for name, etf in etfs.items():
            try:
                hist = yf.Ticker(etf).history(period="3mo")
                if hist.empty:
                    continue
                entry = {"sector": name, "etf": etf}
                for label, period_key in periods.items():
                    if period_key == "5d":
                        sliced = hist.tail(5)
                    elif period_key == "1mo":
                        sliced = hist.tail(21)
                    else:
                        sliced = hist
                    if len(sliced) >= 2:
                        start = float(sliced["Close"].iloc[0])
                        end = float(sliced["Close"].iloc[-1])
                        entry[label] = round(((end - start) / start) * 100, 2)
                    else:
                        entry[label] = 0.0
                results.append(entry)
            except Exception:
                results.append({"sector": name, "etf": etf, "1w": 0, "1m": 0, "3m": 0})
        return results

    result = await asyncio.to_thread(_fetch)
    _set_cached("sector-rotation", result)
    return result
