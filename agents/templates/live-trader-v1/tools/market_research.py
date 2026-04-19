"""Market research toolkit — gives agents real trader intelligence.

Provides: news scanning, earnings calendar, sector momentum, options
unusual activity detection, key level analysis, and macro regime detection.
Uses yfinance (no paid API keys required).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger("market_research")


def _safe_import_yf():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        log.error("yfinance not installed — pip install yfinance")
        return None


def stock_snapshot(ticker: str) -> dict:
    """Comprehensive stock snapshot: price, fundamentals, analyst targets, earnings."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    t = yf.Ticker(ticker)
    info = t.info or {}

    result: dict[str, Any] = {
        "ticker": ticker,
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "prev_close": info.get("previousClose"),
        "open": info.get("open") or info.get("regularMarketOpen"),
        "day_high": info.get("dayHigh"),
        "day_low": info.get("dayLow"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "beta": info.get("beta"),
        "avg_volume": info.get("averageVolume"),
        "volume": info.get("volume"),
        "short_pct": info.get("shortPercentOfFloat"),
        "dividend_yield": info.get("dividendYield"),
    }

    result["analyst_targets"] = {
        "mean": info.get("targetMeanPrice"),
        "low": info.get("targetLowPrice"),
        "high": info.get("targetHighPrice"),
        "consensus": info.get("recommendationKey"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
    }

    try:
        cal = t.calendar
        if cal is not None and isinstance(cal, dict):
            result["earnings_date"] = str(cal.get("Earnings Date", ["N/A"])[0]) if cal.get("Earnings Date") else None
        elif hasattr(cal, "to_dict"):
            d = cal.to_dict()
            result["earnings_date"] = str(list(d.values())[0]) if d else None
    except Exception:
        pass

    try:
        rec = t.recommendations
        if rec is not None and len(rec) > 0:
            recent = rec.tail(5)
            result["recent_ratings"] = recent.to_dict("records") if hasattr(recent, "to_dict") else []
    except Exception:
        pass

    return result


def earnings_calendar(tickers: list[str] | None = None, days_ahead: int = 14) -> dict:
    """Get upcoming earnings dates for a list of tickers or major indices."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    if not tickers:
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                    "SPY", "QQQ", "AMD", "NFLX", "CRM"]

    results = []
    cutoff = datetime.now() + timedelta(days=days_ahead)
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            cal = t.calendar
            if cal is not None and isinstance(cal, dict):
                dates = cal.get("Earnings Date", [])
                for d in dates:
                    if hasattr(d, "date"):
                        d = d.date() if hasattr(d, "date") else d
                    results.append({"ticker": sym, "earnings_date": str(d)})
        except Exception:
            continue

    results.sort(key=lambda x: x.get("earnings_date", ""))
    return {"upcoming_earnings": results, "days_ahead": days_ahead}


def sector_momentum() -> dict:
    """Analyze sector ETF momentum: 1d, 5d, 1mo performance + relative strength."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    etfs = {
        "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
        "XLU": "Utilities", "XLY": "Consumer Disc.", "XLP": "Consumer Staples",
        "XLV": "Healthcare", "XLI": "Industrials", "XLB": "Materials",
        "XLRE": "Real Estate", "XLC": "Communication",
    }
    benchmarks = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000"}

    sectors = []
    for sym, name in {**etfs, **benchmarks}.items():
        try:
            hist = yf.Ticker(sym).history(period="1mo")
            if hist.empty or len(hist) < 2:
                continue
            close = hist["Close"]
            chg_1d = ((close.iloc[-1] / close.iloc[-2]) - 1) * 100 if len(close) >= 2 else 0
            chg_5d = ((close.iloc[-1] / close.iloc[-5]) - 1) * 100 if len(close) >= 5 else 0
            chg_1mo = ((close.iloc[-1] / close.iloc[0]) - 1) * 100
            vol_ratio = (hist["Volume"].iloc[-1] / hist["Volume"].mean()) if hist["Volume"].mean() > 0 else 1
            sectors.append({
                "ticker": sym, "name": name,
                "chg_1d": round(chg_1d, 2), "chg_5d": round(chg_5d, 2),
                "chg_1mo": round(chg_1mo, 2), "vol_ratio": round(vol_ratio, 2),
                "is_benchmark": sym in benchmarks,
            })
        except Exception:
            continue

    sectors.sort(key=lambda x: x.get("chg_1d", 0), reverse=True)
    return {"sectors": sectors}


def key_levels(ticker: str, period: str = "3mo") -> dict:
    """Calculate key support/resistance levels, pivot points, and moving averages."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    hist = yf.Ticker(ticker).history(period=period)
    if hist.empty or len(hist) < 20:
        return {"error": f"Insufficient data for {ticker}"}

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]

    last_close = float(close.iloc[-1])
    last_high = float(high.iloc[-1])
    last_low = float(low.iloc[-1])

    pivot = (last_high + last_low + last_close) / 3
    r1 = 2 * pivot - last_low
    s1 = 2 * pivot - last_high
    r2 = pivot + (last_high - last_low)
    s2 = pivot - (last_high - last_low)

    sma_20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
    sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    ema_9 = float(close.ewm(span=9).mean().iloc[-1])
    ema_21 = float(close.ewm(span=21).mean().iloc[-1])

    recent_highs = sorted(high.nlargest(5).values.tolist(), reverse=True)
    recent_lows = sorted(low.nsmallest(5).values.tolist())

    vwap = float((hist["Close"] * hist["Volume"]).sum() / hist["Volume"].sum()) if hist["Volume"].sum() > 0 else last_close

    return {
        "ticker": ticker,
        "price": last_close,
        "pivot_points": {"pivot": round(pivot, 2), "r1": round(r1, 2), "r2": round(r2, 2), "s1": round(s1, 2), "s2": round(s2, 2)},
        "moving_averages": {
            "ema_9": round(ema_9, 2), "ema_21": round(ema_21, 2),
            "sma_20": round(sma_20, 2) if sma_20 else None,
            "sma_50": round(sma_50, 2) if sma_50 else None,
        },
        "ema_trend": "bullish" if ema_9 > ema_21 else "bearish",
        "price_vs_sma20": "above" if sma_20 and last_close > sma_20 else "below",
        "vwap": round(vwap, 2),
        "recent_resistance": [round(h, 2) for h in recent_highs[:3]],
        "recent_support": [round(l, 2) for l in recent_lows[:3]],
    }


def options_unusual_activity(ticker: str) -> dict:
    """Detect unusual options activity: volume spikes, put/call ratio, skew."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    t = yf.Ticker(ticker)
    try:
        expirations = t.options
        if not expirations:
            return {"ticker": ticker, "error": "No options available"}
    except Exception:
        return {"ticker": ticker, "error": "Failed to fetch options data"}

    total_call_vol = 0
    total_put_vol = 0
    total_call_oi = 0
    total_put_oi = 0
    unusual_strikes: list[dict] = []

    for exp in expirations[:3]:
        try:
            chain = t.option_chain(exp)
            for _, row in chain.calls.iterrows():
                vol = int(row.get("volume", 0) or 0)
                oi = int(row.get("openInterest", 0) or 0)
                total_call_vol += vol
                total_call_oi += oi
                if oi > 0 and vol > oi * 2:
                    unusual_strikes.append({
                        "expiry": exp, "type": "call",
                        "strike": float(row["strike"]),
                        "volume": vol, "oi": oi,
                        "vol_oi_ratio": round(vol / oi, 1),
                        "iv": round(float(row.get("impliedVolatility", 0) or 0) * 100, 1),
                    })
            for _, row in chain.puts.iterrows():
                vol = int(row.get("volume", 0) or 0)
                oi = int(row.get("openInterest", 0) or 0)
                total_put_vol += vol
                total_put_oi += oi
                if oi > 0 and vol > oi * 2:
                    unusual_strikes.append({
                        "expiry": exp, "type": "put",
                        "strike": float(row["strike"]),
                        "volume": vol, "oi": oi,
                        "vol_oi_ratio": round(vol / oi, 1),
                        "iv": round(float(row.get("impliedVolatility", 0) or 0) * 100, 1),
                    })
        except Exception:
            continue

    pc_ratio = round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else None
    unusual_strikes.sort(key=lambda x: x.get("vol_oi_ratio", 0), reverse=True)

    return {
        "ticker": ticker,
        "total_call_volume": total_call_vol,
        "total_put_volume": total_put_vol,
        "put_call_ratio": pc_ratio,
        "put_call_oi_ratio": round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None,
        "sentiment": "bearish" if pc_ratio and pc_ratio > 1.2 else "bullish" if pc_ratio and pc_ratio < 0.7 else "neutral",
        "unusual_strikes": unusual_strikes[:10],
    }


def macro_regime() -> dict:
    """Detect current macro regime: VIX level, yield curve, market breadth."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    result: dict[str, Any] = {}

    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if not vix.empty:
            vix_val = float(vix["Close"].iloc[-1])
            vix_5d_avg = float(vix["Close"].mean())
            result["vix"] = {
                "current": round(vix_val, 2),
                "5d_avg": round(vix_5d_avg, 2),
                "regime": "extreme_fear" if vix_val > 30 else "fear" if vix_val > 20 else "complacent" if vix_val < 13 else "normal",
            }
    except Exception:
        pass

    try:
        tickers = {"2y": "^IRX", "10y": "^TNX"}
        yields = {}
        for name, sym in tickers.items():
            h = yf.Ticker(sym).history(period="5d")
            if not h.empty:
                yields[name] = round(float(h["Close"].iloc[-1]), 3)
        if "2y" in yields and "10y" in yields:
            spread = yields["10y"] - yields["2y"]
            result["yield_curve"] = {**yields, "spread_10y_2y": round(spread, 3), "inverted": spread < 0}
    except Exception:
        pass

    try:
        spy = yf.Ticker("SPY").history(period="3mo")
        if not spy.empty and len(spy) >= 50:
            sma50 = float(spy["Close"].rolling(50).mean().iloc[-1])
            current = float(spy["Close"].iloc[-1])
            result["spy"] = {
                "price": round(current, 2),
                "sma_50": round(sma50, 2),
                "above_50sma": current > sma50,
            }
    except Exception:
        pass

    return result


def position_health_check(ticker: str, entry_price: float, option_type: str | None = None,
                          strike: float | None = None, expiry: str | None = None) -> dict:
    """Comprehensive health check for an open position with exit recommendation."""
    yf = _safe_import_yf()
    if not yf:
        return {"error": "yfinance not available"}

    t = yf.Ticker(ticker)
    info = t.info or {}
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or 0

    hist = t.history(period="1mo")
    if hist.empty:
        return {"error": f"No data for {ticker}"}

    close = hist["Close"]

    rsi_14 = _calc_rsi(close, 14)
    sma_20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None

    pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0

    signals = []
    if rsi_14 and rsi_14 > 70:
        signals.append("RSI overbought — consider taking profits")
    elif rsi_14 and rsi_14 < 30:
        signals.append("RSI oversold — potential bounce")

    if sma_20 and current_price < sma_20:
        signals.append("Below 20-SMA — weakness")
    elif sma_20 and current_price > sma_20 * 1.05:
        signals.append("Extended above 20-SMA")

    if pnl_pct < -15:
        signals.append("SIGNIFICANT LOSS — review stop-loss")
    elif pnl_pct > 20:
        signals.append("Strong profit — consider trailing stop or partial exit")

    if expiry:
        try:
            days_to_expiry = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.now()).days
            if days_to_expiry <= 3:
                signals.append("EXPIRING SOON — high theta decay risk")
            elif days_to_expiry <= 7:
                signals.append("Within 1 week of expiry — accelerating theta")
        except ValueError:
            pass

    recommendation = "HOLD"
    if any("SIGNIFICANT LOSS" in s for s in signals) or any("EXPIRING SOON" in s for s in signals):
        recommendation = "CLOSE — high risk"
    elif any("taking profits" in s for s in signals) and pnl_pct > 10:
        recommendation = "TAKE_PROFITS — partial or full exit"
    elif pnl_pct > 30:
        recommendation = "TRAIL — set trailing stop"

    return {
        "ticker": ticker,
        "current_price": round(current_price, 2) if current_price else None,
        "entry_price": entry_price,
        "pnl_pct": round(pnl_pct, 2),
        "rsi_14": round(rsi_14, 2) if rsi_14 else None,
        "sma_20": round(sma_20, 2) if sma_20 else None,
        "signals": signals,
        "recommendation": recommendation,
        "option_context": {"type": option_type, "strike": strike, "expiry": expiry} if option_type else None,
    }


def _calc_rsi(series, period: int = 14) -> float | None:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
    return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# CLI entry point — agent can run: python market_research.py <function> <args_json>
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: market_research.py <function> [args_json]"}))
        sys.exit(1)

    func_name = sys.argv[1]
    args_raw = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    funcs = {
        "stock_snapshot": stock_snapshot,
        "earnings_calendar": earnings_calendar,
        "sector_momentum": sector_momentum,
        "key_levels": key_levels,
        "options_unusual_activity": options_unusual_activity,
        "macro_regime": macro_regime,
        "position_health_check": position_health_check,
    }

    fn = funcs.get(func_name)
    if not fn:
        print(json.dumps({"error": f"Unknown function: {func_name}. Available: {list(funcs.keys())}"}))
        sys.exit(1)

    if isinstance(args_raw, dict):
        result = fn(**args_raw)
    elif isinstance(args_raw, list):
        result = fn(*args_raw)
    else:
        result = fn(args_raw)

    print(json.dumps(result, default=str, indent=2))
