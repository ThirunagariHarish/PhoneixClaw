"""Technical analysis check for position monitoring.

Computes RSI, MACD, Bollinger Bands, support/resistance for a ticker
and scores how 'exitable' the position is.

Usage:
    python ta_check.py --ticker AAPL --side buy --output ta.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def compute_ta(ticker: str, side: str) -> dict:
    """Compute TA indicators and exit urgency score for a position."""
    result = {
        "ticker": ticker,
        "side": side,
        "exit_urgency": 0,
        "indicators": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        import yfinance as yf
        import numpy as np

        data = yf.download(ticker, period="5d", interval="5m", progress=False)
        if data.empty or len(data) < 30:
            result["error"] = "insufficient data"
            return result
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"]
        high = data["High"]
        low = data["Low"]

        # RSI(14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        current_rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0
        result["indicators"]["rsi_14"] = round(current_rsi, 1)

        if side == "buy" and current_rsi > 75:
            result["exit_urgency"] += 20
            result["indicators"]["rsi_signal"] = "overbought"
        elif side == "sell" and current_rsi < 25:
            result["exit_urgency"] += 20
            result["indicators"]["rsi_signal"] = "oversold"

        # MACD histogram (12/26/9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        hist = float((macd.iloc[-1] - signal_line.iloc[-1]))
        result["indicators"]["macd_histogram"] = round(hist, 4)

        if side == "buy" and hist < 0:
            result["exit_urgency"] += 10
            result["indicators"]["macd_signal"] = "bearish_cross"
        elif side == "sell" and hist > 0:
            result["exit_urgency"] += 10
            result["indicators"]["macd_signal"] = "bullish_cross"

        # Bollinger Bands (20, 2-std)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_upper = float((sma20 + 2 * std20).iloc[-1])
        bb_lower = float((sma20 - 2 * std20).iloc[-1])
        current_price = float(close.iloc[-1])
        result["indicators"]["bb_upper"] = round(bb_upper, 2)
        result["indicators"]["bb_lower"] = round(bb_lower, 2)
        result["indicators"]["current_price"] = round(current_price, 2)

        if side == "buy" and current_price >= bb_upper:
            result["exit_urgency"] += 15
            result["indicators"]["bb_signal"] = "above_upper_band"
        elif side == "sell" and current_price <= bb_lower:
            result["exit_urgency"] += 15
            result["indicators"]["bb_signal"] = "below_lower_band"

        # Support/Resistance (20-bar high/low)
        recent_high = float(high.iloc[-20:].max())
        recent_low = float(low.iloc[-20:].min())
        result["indicators"]["resistance"] = round(recent_high, 2)
        result["indicators"]["support"] = round(recent_low, 2)

        if side == "buy" and current_price >= recent_high * 0.98:
            result["exit_urgency"] += 10
            result["indicators"]["sr_signal"] = "near_resistance"
        elif side == "sell" and current_price <= recent_low * 1.02:
            result["exit_urgency"] += 10
            result["indicators"]["sr_signal"] = "near_support"

    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    parser = argparse.ArgumentParser(description="Position TA check")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--output", default="ta.json")
    args = parser.parse_args()

    result = compute_ta(args.ticker, args.side)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
