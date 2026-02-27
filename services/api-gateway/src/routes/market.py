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


# ── Gamma Exposure (GEX) ────────────────────────────────────────────────────

@router.get("/gex")
async def gamma_exposure(symbol: str = "SPY"):
    cache_key = f"gex-{symbol}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        from scipy.stats import norm
        import math

        t = yf.Ticker(symbol)
        spot = getattr(t.fast_info, "last_price", None) or 0
        if not spot:
            return {"symbol": symbol, "total_gex": 0, "strikes": [], "flip_point": 0, "regime": "N/A"}

        expirations = t.options[:4] if len(t.options) >= 4 else t.options
        strike_gex: dict[float, float] = {}

        for exp in expirations:
            try:
                chain = t.option_chain(exp)
                for _, row in chain.calls.iterrows():
                    strike = float(row["strike"])
                    oi = int(row.get("openInterest", 0) or 0)
                    iv = float(row.get("impliedVolatility", 0.3) or 0.3)
                    if oi <= 0 or strike <= 0:
                        continue
                    d1 = (math.log(spot / strike) + 0.5 * iv * iv) / (iv + 1e-9)
                    gamma = norm.pdf(d1) / (spot * iv + 1e-9)
                    gex = gamma * oi * 100 * spot
                    strike_gex[strike] = strike_gex.get(strike, 0) + gex

                for _, row in chain.puts.iterrows():
                    strike = float(row["strike"])
                    oi = int(row.get("openInterest", 0) or 0)
                    iv = float(row.get("impliedVolatility", 0.3) or 0.3)
                    if oi <= 0 or strike <= 0:
                        continue
                    d1 = (math.log(spot / strike) + 0.5 * iv * iv) / (iv + 1e-9)
                    gamma = norm.pdf(d1) / (spot * iv + 1e-9)
                    gex = -gamma * oi * 100 * spot
                    strike_gex[strike] = strike_gex.get(strike, 0) + gex
            except Exception:
                continue

        total_gex = sum(strike_gex.values())
        regime = "Long Gamma (Stabilizing)" if total_gex > 0 else "Short Gamma (Volatile)"

        flip_point = 0
        sorted_strikes = sorted(strike_gex.items())
        for i in range(len(sorted_strikes) - 1):
            s1, g1 = sorted_strikes[i]
            s2, g2 = sorted_strikes[i + 1]
            if g1 * g2 < 0:
                flip_point = round((s1 + s2) / 2, 2)
                break

        near_spot = [(s, round(g, 0)) for s, g in sorted_strikes if abs(s - spot) / spot < 0.05]

        return {
            "symbol": symbol,
            "spot": round(spot, 2),
            "total_gex": round(total_gex, 0),
            "regime": regime,
            "flip_point": flip_point,
            "strikes": [{"strike": s, "gex": g} for s, g in near_spot],
        }

    result = await asyncio.to_thread(_fetch)
    _set_cached(cache_key, result)
    return result


# ── Market Internals ─────────────────────────────────────────────────────────

@router.get("/internals")
async def market_internals():
    cached = _get_cached("internals")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        indicators = {
            "TICK": {"ticker": "^TICK", "bullish": 800, "bearish": -800},
            "TRIN": {"ticker": "^TRIN", "bullish": 0.7, "bearish": 1.3},
            "ADD": {"ticker": "^ADD", "bullish": 1000, "bearish": -1000},
            "VIX": {"ticker": "^VIX", "bullish": None, "bearish": None},
        }
        results = []
        for name, cfg in indicators.items():
            try:
                hist = yf.Ticker(cfg["ticker"]).history(period="2d")
                if not hist.empty:
                    val = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else val
                    change = val - prev

                    if name == "TRIN":
                        zone = "Bullish" if val < cfg["bullish"] else "Bearish" if val > cfg["bearish"] else "Neutral"
                    elif name == "VIX":
                        zone = "Risk-Off" if change > 1 else "Risk-On" if change < -1 else "Neutral"
                    elif cfg["bullish"] is not None:
                        zone = "Bullish" if val > cfg["bullish"] else "Bearish" if val < cfg["bearish"] else "Neutral"
                    else:
                        zone = "Neutral"

                    results.append({"name": name, "value": round(val, 2), "change": round(change, 2), "zone": zone})
                else:
                    results.append({"name": name, "value": 0, "change": 0, "zone": "N/A"})
            except Exception:
                results.append({"name": name, "value": 0, "change": 0, "zone": "N/A"})
        return results

    result = await asyncio.to_thread(_fetch)
    _set_cached("internals", result)
    return result


# ── VIX Term Structure ───────────────────────────────────────────────────────

@router.get("/vix-term-structure")
async def vix_term_structure():
    cached = _get_cached("vix-term")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        vix_tickers = {
            "VIX9D": "^VIX9D",
            "VIX": "^VIX",
            "VIX3M": "^VIX3M",
            "VIX6M": "^VIX6M",
        }
        points = []
        for label, ticker in vix_tickers.items():
            try:
                hist = yf.Ticker(ticker).history(period="5d")
                if not hist.empty:
                    val = round(float(hist["Close"].iloc[-1]), 2)
                    prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else val
                    points.append({"term": label, "value": val, "change": round(val - prev, 2)})
            except Exception:
                points.append({"term": label, "value": 0, "change": 0})

        if len(points) >= 2:
            front = points[0]["value"] if points[0]["value"] > 0 else points[1]["value"]
            back = points[-1]["value"]
            if front > 0 and back > 0:
                regime = "Backwardation (Fear)" if front > back else "Contango (Calm)"
            else:
                regime = "N/A"
        else:
            regime = "N/A"

        return {"points": points, "regime": regime}

    result = await asyncio.to_thread(_fetch)
    _set_cached("vix-term", result)
    return result


# ── Premarket Gap Scanner ────────────────────────────────────────────────────

@router.get("/premarket-gaps")
async def premarket_gaps():
    cached = _get_cached("premarket-gaps")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "NFLX", "CRM", "COIN", "PLTR", "SOFI", "BA", "DIS",
            "JPM", "PYPL", "SQ", "ROKU", "SNAP", "SPY", "QQQ",
        ]
        gaps = []
        for ticker in watchlist:
            try:
                t = yf.Ticker(ticker)
                info = t.info
                pre_price = info.get("preMarketPrice") or info.get("regularMarketPrice", 0)
                prev_close = info.get("regularMarketPreviousClose", 0)
                if pre_price and prev_close and prev_close > 0:
                    gap_pct = round(((pre_price - prev_close) / prev_close) * 100, 2)
                    if abs(gap_pct) >= 0.5:
                        gaps.append({
                            "ticker": ticker,
                            "pre_price": round(float(pre_price), 2),
                            "prev_close": round(float(prev_close), 2),
                            "gap_pct": gap_pct,
                            "volume": info.get("preMarketVolume") or info.get("volume", 0),
                        })
            except Exception:
                pass
        gaps.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
        return {"gappers_up": [g for g in gaps if g["gap_pct"] > 0][:10],
                "gappers_down": [g for g in gaps if g["gap_pct"] < 0][:10]}

    result = await asyncio.to_thread(_fetch)
    _set_cached("premarket-gaps", result)
    return result


# ── SPX Key Levels ───────────────────────────────────────────────────────────

@router.get("/spx-levels")
async def spx_key_levels():
    cached = _get_cached("spx-levels")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        spy = yf.Ticker("SPY")
        hist_5d = spy.history(period="5d")
        hist_1mo = spy.history(period="1mo")

        levels = {}
        if len(hist_5d) >= 2:
            yesterday = hist_5d.iloc[-2]
            levels["prev_high"] = round(float(yesterday["High"]), 2)
            levels["prev_low"] = round(float(yesterday["Low"]), 2)
            levels["prev_close"] = round(float(yesterday["Close"]), 2)
            levels["current"] = round(float(hist_5d["Close"].iloc[-1]), 2)

            h, l, c = float(yesterday["High"]), float(yesterday["Low"]), float(yesterday["Close"])
            pp = (h + l + c) / 3
            levels["pivot"] = round(pp, 2)
            levels["r1"] = round(2 * pp - l, 2)
            levels["r2"] = round(pp + (h - l), 2)
            levels["s1"] = round(2 * pp - h, 2)
            levels["s2"] = round(pp - (h - l), 2)

        if len(hist_1mo) >= 5:
            week = hist_1mo.tail(5)
            levels["week_high"] = round(float(week["High"].max()), 2)
            levels["week_low"] = round(float(week["Low"].min()), 2)
            levels["month_high"] = round(float(hist_1mo["High"].max()), 2)
            levels["month_low"] = round(float(hist_1mo["Low"].min()), 2)

        if len(hist_5d) >= 1:
            today = hist_5d.iloc[-1]
            typical = (float(today["High"]) + float(today["Low"]) + float(today["Close"])) / 3
            cum_vol = float(today["Volume"])
            levels["vwap_approx"] = round(typical, 2)

        return levels

    result = await asyncio.to_thread(_fetch)
    _set_cached("spx-levels", result)
    return result


# ── Options Flow Summary ────────────────────────────────────────────────────

@router.get("/options-flow")
async def options_flow():
    cached = _get_cached("options-flow")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        symbols = ["SPY", "QQQ"]
        results = []
        for sym in symbols:
            try:
                t = yf.Ticker(sym)
                exps = t.options[:3] if len(t.options) >= 3 else t.options
                total_call_vol = 0
                total_put_vol = 0
                total_call_oi = 0
                total_put_oi = 0
                unusual = []

                for exp in exps:
                    chain = t.option_chain(exp)
                    for _, row in chain.calls.iterrows():
                        vol = int(row.get("volume", 0) or 0)
                        oi = int(row.get("openInterest", 0) or 0)
                        total_call_vol += vol
                        total_call_oi += oi
                        if oi > 0 and vol > oi * 2:
                            unusual.append({"strike": float(row["strike"]), "type": "CALL", "volume": vol, "oi": oi, "ratio": round(vol / max(oi, 1), 1), "exp": exp})

                    for _, row in chain.puts.iterrows():
                        vol = int(row.get("volume", 0) or 0)
                        oi = int(row.get("openInterest", 0) or 0)
                        total_put_vol += vol
                        total_put_oi += oi
                        if oi > 0 and vol > oi * 2:
                            unusual.append({"strike": float(row["strike"]), "type": "PUT", "volume": vol, "oi": oi, "ratio": round(vol / max(oi, 1), 1), "exp": exp})

                unusual.sort(key=lambda x: x["volume"], reverse=True)
                results.append({
                    "symbol": sym,
                    "call_volume": total_call_vol,
                    "put_volume": total_put_vol,
                    "call_oi": total_call_oi,
                    "put_oi": total_put_oi,
                    "pc_ratio": round(total_put_vol / max(total_call_vol, 1), 3),
                    "unusual_activity": unusual[:5],
                })
            except Exception as e:
                logger.warning("Options flow fetch failed for %s: %s", sym, e)
                results.append({"symbol": sym, "call_volume": 0, "put_volume": 0, "call_oi": 0, "put_oi": 0, "pc_ratio": 0, "unusual_activity": []})
        return results

    result = await asyncio.to_thread(_fetch)
    _set_cached("options-flow", result)
    return result


# ── Correlation Matrix ───────────────────────────────────────────────────────

@router.get("/correlations")
async def correlations():
    cached = _get_cached("correlations")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        import numpy as np

        tickers = {"SPY": "SPY", "QQQ": "QQQ", "TLT": "TLT", "GLD": "GLD", "UUP": "UUP", "VIX": "^VIX", "BTC": "BTC-USD"}
        closes = {}
        for label, ticker in tickers.items():
            try:
                hist = yf.Ticker(ticker).history(period="3mo")
                if not hist.empty:
                    closes[label] = hist["Close"].pct_change().dropna().values[-30:]
            except Exception:
                pass

        labels = list(closes.keys())
        n = len(labels)
        matrix = []
        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    row.append(1.0)
                else:
                    a, b = closes[labels[i]], closes[labels[j]]
                    min_len = min(len(a), len(b))
                    if min_len > 5:
                        corr = float(np.corrcoef(a[:min_len], b[:min_len])[0, 1])
                        row.append(round(corr, 3))
                    else:
                        row.append(0)
            matrix.append(row)
        return {"labels": labels, "matrix": matrix}

    result = await asyncio.to_thread(_fetch)
    _set_cached("correlations", result)
    return result


# ── Volatility Dashboard ────────────────────────────────────────────────────

@router.get("/volatility")
async def volatility_dashboard():
    cached = _get_cached("volatility")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        import numpy as np

        spy = yf.Ticker("SPY")
        hist = spy.history(period="1y")
        if len(hist) < 30:
            return {"error": "insufficient data"}

        returns = hist["Close"].pct_change().dropna()

        hv_10 = round(float(returns.tail(10).std() * np.sqrt(252) * 100), 2)
        hv_20 = round(float(returns.tail(20).std() * np.sqrt(252) * 100), 2)
        hv_30 = round(float(returns.tail(30).std() * np.sqrt(252) * 100), 2)

        vix_hist = yf.Ticker("^VIX").history(period="1y")
        iv_current = 0.0
        iv_high = 0.0
        iv_low = 100.0
        if not vix_hist.empty:
            iv_current = round(float(vix_hist["Close"].iloc[-1]), 2)
            iv_high = round(float(vix_hist["Close"].max()), 2)
            iv_low = round(float(vix_hist["Close"].min()), 2)

        iv_range = iv_high - iv_low
        iv_rank = round(((iv_current - iv_low) / iv_range * 100) if iv_range > 0 else 50, 1)
        iv_percentile = round(float((vix_hist["Close"] < iv_current).mean() * 100) if not vix_hist.empty else 50, 1)
        hv_iv_spread = round(iv_current - hv_30, 2)

        return {
            "iv_current": iv_current,
            "iv_rank": iv_rank,
            "iv_percentile": iv_percentile,
            "iv_high_52w": iv_high,
            "iv_low_52w": iv_low,
            "hv_10": hv_10,
            "hv_20": hv_20,
            "hv_30": hv_30,
            "hv_iv_spread": hv_iv_spread,
        }

    result = await asyncio.to_thread(_fetch)
    _set_cached("volatility", result)
    return result


# ── Premarket Movers ─────────────────────────────────────────────────────────

@router.get("/premarket-movers")
async def premarket_movers():
    cached = _get_cached("premarket-movers")
    if cached:
        return cached

    def _fetch():
        import yfinance as yf
        watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "NFLX", "CRM", "COIN", "PLTR", "SOFI", "BA", "DIS",
            "SPY", "QQQ", "IWM", "PYPL", "SQ", "ROKU", "SNAP",
        ]
        movers = []
        for ticker in watchlist:
            try:
                info = yf.Ticker(ticker).info
                pre = info.get("preMarketPrice")
                prev = info.get("regularMarketPreviousClose", 0)
                reg = info.get("regularMarketPrice", prev)
                if pre and prev and prev > 0:
                    change_pct = round(((pre - prev) / prev) * 100, 2)
                    movers.append({
                        "ticker": ticker,
                        "pre_price": round(float(pre), 2),
                        "prev_close": round(float(prev), 2),
                        "change_pct": change_pct,
                        "volume": info.get("preMarketVolume", 0) or 0,
                    })
                elif reg and prev and prev > 0:
                    change_pct = round(((reg - prev) / prev) * 100, 2)
                    movers.append({
                        "ticker": ticker,
                        "pre_price": round(float(reg), 2),
                        "prev_close": round(float(prev), 2),
                        "change_pct": change_pct,
                        "volume": info.get("volume", 0) or 0,
                    })
            except Exception:
                pass
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return movers[:15]

    result = await asyncio.to_thread(_fetch)
    _set_cached("premarket-movers", result)
    return result


# ── Day Trade P&L ────────────────────────────────────────────────────────────

@router.get("/day-pnl")
async def day_trade_pnl():
    """Returns today's trading P&L from the local trades database, or mock data if DB unavailable."""
    cached = _get_cached("day-pnl")
    if cached:
        return cached

    try:
        from shared.database import SessionLocal
        from shared.models.trade import Trade
        from sqlalchemy import func

        today = datetime.utcnow().date()
        db = SessionLocal()
        try:
            trades = db.query(Trade).filter(func.date(Trade.created_at) == today).all()
            if not trades:
                return {"date": str(today), "total_pnl": 0, "trade_count": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0, "trades": []}

            pnls = [float(t.realized_pnl or 0) for t in trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            result = {
                "date": str(today),
                "total_pnl": round(sum(pnls), 2),
                "trade_count": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / max(len(pnls), 1) * 100, 1),
                "avg_win": round(sum(wins) / max(len(wins), 1), 2),
                "avg_loss": round(sum(losses) / max(len(losses), 1), 2),
                "trades": [
                    {"ticker": t.ticker, "side": t.action, "pnl": round(float(t.realized_pnl or 0), 2),
                     "time": t.created_at.strftime("%H:%M") if t.created_at else ""}
                    for t in trades[-20:]
                ],
            }
            _set_cached("day-pnl", result)
            return result
        finally:
            db.close()
    except Exception as e:
        logger.warning("Day P&L fetch failed (DB may be unavailable): %s", e)
        return {"date": str(datetime.utcnow().date()), "total_pnl": 0, "trade_count": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0, "trades": []}
