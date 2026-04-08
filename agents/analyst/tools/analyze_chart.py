"""Technical chart analysis using yfinance."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


async def analyze_chart(
    ticker: str,
    interval: str = "15m",
    lookback_days: int = 5,
) -> dict:
    """Download OHLCV data and compute technical indicators.
    Computes RSI (14), MACD (12/26/9), Bollinger Bands (20/2), VWAP,
    EMA 9/21/50, SMA 200, support/resistance, and pattern detection.
    Args:
        ticker: Stock ticker symbol.
        interval: yfinance interval (e.g. '1m', '5m', '15m', '1h').
        lookback_days: Number of days of historical data.
    Returns:
        Dict with all indicators and a 'signal' key ('bullish'|'bearish'|'neutral').
    """
    try:
        import pandas as pd
        import yfinance as yf
    except ImportError as exc:
        logger.warning("analyze_chart: missing dependency %s", exc)
        return {"signal": "neutral", "error": str(exc), "patterns": [], "current_price": 0.0}
    try:
        period = f"{max(lookback_days, 5)}d"

        def _download() -> "pd.DataFrame":
            return yf.download(
                ticker, period=period, interval=interval, progress=False, auto_adjust=True
            )

        # yf.download is a blocking network call — run it in a thread pool
        data = await asyncio.to_thread(_download)
        if data is None or len(data) < 20:
            logger.warning("analyze_chart: insufficient data for %s", ticker)
            return {"signal": "neutral", "error": "insufficient data", "patterns": [], "current_price": 0.0}
        close = data["Close"].squeeze()
        high = data["High"].squeeze()
        low = data["Low"].squeeze()
        volume = data["Volume"].squeeze()
        # --- RSI (14) ---
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])
        # --- MACD (12/26/9) ---
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        macd_val = float(macd_line.iloc[-1])
        macd_signal_val = float(signal_line.iloc[-1])
        macd_hist_val = float(macd_hist.iloc[-1])
        # --- Bollinger Bands (20/2) ---
        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        bb_upper = float((sma20 + 2 * std20).iloc[-1])
        bb_middle = float(sma20.iloc[-1])
        bb_lower = float((sma20 - 2 * std20).iloc[-1])
        current_close = float(close.iloc[-1])
        if current_close > bb_upper:
            bb_position = "above"
        elif current_close < bb_lower:
            bb_position = "below"
        else:
            bb_position = "inside"
        # --- VWAP ---
        typical_price = (high + low + close) / 3
        try:
            vwap = float((typical_price * volume).sum() / volume.sum())
        except Exception:
            vwap = current_close
        price_vs_vwap = "above" if current_close > vwap else "below"
        # --- EMAs and SMA ---
        ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        sma200_series = close.rolling(window=200).mean()
        sma200 = float(sma200_series.iloc[-1]) if not pd.isna(sma200_series.iloc[-1]) else float(close.mean())
        # --- Trend ---
        if ema9 > ema21 > ema50 and current_close > sma200:
            trend = "bullish"
        elif ema9 < ema21 < ema50 and current_close < sma200:
            trend = "bearish"
        else:
            trend = "neutral"
        # --- Support / Resistance (local min/max last 20 candles) ---
        recent_low = data["Low"].tail(20)
        recent_high = data["High"].tail(20)
        support = float(recent_low.min())
        resistance = float(recent_high.max())
        # --- Volume ---
        avg_volume = float(volume.rolling(window=20).mean().iloc[-1]) if len(volume) >= 20 else float(volume.mean())
        current_volume = float(volume.iloc[-1])
        # --- Pattern Detection ---
        patterns: list[str] = []
        if rsi < 30:
            patterns.append("Oversold")
        elif rsi > 70:
            patterns.append("Overbought")
        if bb_position == "above" and current_volume > avg_volume * 1.5:
            patterns.append("Breakout")
        elif bb_position == "below" and current_volume > avg_volume * 1.5:
            patterns.append("Breakdown")
        if len(close) >= 10:
            recent_5 = close.tail(5)
            prior_5 = close.iloc[-10:-5]
            prior_range = float(prior_5.max() - prior_5.min())
            recent_range = float(recent_5.max() - recent_5.min())
            prior_direction = float(prior_5.iloc[-1] - prior_5.iloc[0])
            if prior_direction > 0 and recent_range < prior_range * 0.5 and current_volume < avg_volume:
                patterns.append("Bull Flag")
            elif prior_direction < 0 and recent_range < prior_range * 0.5 and current_volume < avg_volume:
                patterns.append("Bear Flag")
        # --- Overall Signal ---
        bullish_signals = sum([
            trend == "bullish",
            macd_hist_val > 0,
            bb_position == "inside" and rsi > 50,
            price_vs_vwap == "above",
            "Breakout" in patterns,
            "Oversold" in patterns,
        ])
        bearish_signals = sum([
            trend == "bearish",
            macd_hist_val < 0,
            bb_position == "inside" and rsi < 50,
            price_vs_vwap == "below",
            "Breakdown" in patterns,
            "Overbought" in patterns,
        ])
        if bullish_signals > bearish_signals + 1:
            signal = "bullish"
        elif bearish_signals > bullish_signals + 1:
            signal = "bearish"
        else:
            signal = "neutral"
        return {
            "rsi": round(rsi, 2),
            "macd": round(macd_val, 4),
            "macd_signal": round(macd_signal_val, 4),
            "macd_histogram": round(macd_hist_val, 4),
            "bb_upper": round(bb_upper, 2),
            "bb_middle": round(bb_middle, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_position": bb_position,
            "vwap": round(vwap, 2),
            "price_vs_vwap": price_vs_vwap,
            "ema_9": round(ema9, 2),
            "ema_21": round(ema21, 2),
            "ema_50": round(ema50, 2),
            "sma_200": round(sma200, 2),
            "trend": trend,
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "patterns": patterns,
            "signal": signal,
            "current_price": round(current_close, 2),
            "volume": current_volume,
            "avg_volume": avg_volume,
        }
    except Exception as exc:
        logger.warning("analyze_chart error for %s: %s", ticker, exc)
        return {"signal": "neutral", "error": str(exc), "patterns": [], "current_price": 0.0}
async def _main_async(args: argparse.Namespace) -> None:
    result = await analyze_chart(args.ticker, args.interval, args.lookback_days)
    print(json.dumps(result, indent=2, default=str))
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze chart for a ticker")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL)")
    parser.add_argument("--interval", default="15m", help="Chart interval (default: 15m)")
    parser.add_argument("--lookback-days", type=int, default=5, help="Days of history")
    args = parser.parse_args()
    asyncio.run(_main_async(args))
