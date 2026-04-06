"""Level scanner — scan tickers for 52-week highs/lows and support/resistance.

Usage:
    python level_scanner.py --tickers SPY,QQQ,AAPL --output levels.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def scan_levels(strategy: dict) -> dict:
    """Scan for 52-week level signals based on strategy config."""
    universe = strategy.get("universe", strategy.get("tickers", []))
    if not universe:
        return {"signal": None, "reason": "No tickers in universe"}

    threshold_pct = strategy.get("threshold_pct", 5.0)  # within 5% of 52w extreme

    candidates = []
    for ticker in universe:
        result = _check_ticker(ticker, threshold_pct)
        if result:
            candidates.append(result)

    if not candidates:
        return {"signal": None, "reason": "No tickers near 52w extremes"}

    # Take the highest score
    best = max(candidates, key=lambda c: c.get("confidence", 0))
    return best


def _check_ticker(ticker: str, threshold_pct: float) -> dict | None:
    try:
        import yfinance as yf
        import numpy as np

        data = yf.download(ticker, period="1y", progress=False)
        if data.empty or len(data) < 30:
            return None
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"]
        high = data["High"]
        low = data["Low"]

        cur_price = float(close.iloc[-1])
        high_52w = float(high.max())
        low_52w = float(low.min())

        dist_from_low = (cur_price - low_52w) / low_52w * 100
        dist_from_high = (high_52w - cur_price) / high_52w * 100

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        cur_rsi = float(rsi.iloc[-1]) if not rsi.empty else 50

        # 52w low + oversold = buy
        if dist_from_low <= threshold_pct and cur_rsi < 35:
            return {
                "signal": "BUY",
                "ticker": ticker,
                "direction": "buy",
                "confidence": 0.70 + (35 - cur_rsi) / 100,
                "reason": (f"{ticker} within {dist_from_low:.1f}% of 52w low (${low_52w:.2f}); "
                           f"RSI={cur_rsi:.0f} (oversold)"),
                "current_price": cur_price,
                "52w_low": low_52w,
                "52w_high": high_52w,
                "rsi_14": cur_rsi,
                "strategy_type": "52w_low_bounce",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # 52w high + overbought = sell
        if dist_from_high <= threshold_pct and cur_rsi > 70:
            return {
                "signal": "SELL",
                "ticker": ticker,
                "direction": "sell",
                "confidence": 0.70 + (cur_rsi - 70) / 100,
                "reason": (f"{ticker} within {dist_from_high:.1f}% of 52w high (${high_52w:.2f}); "
                           f"RSI={cur_rsi:.0f} (overbought)"),
                "current_price": cur_price,
                "52w_low": low_52w,
                "52w_high": high_52w,
                "rsi_14": cur_rsi,
                "strategy_type": "52w_high_rejection",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Level scanner")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--threshold", type=float, default=5.0)
    parser.add_argument("--output", default="levels.json")
    args = parser.parse_args()

    universe = [t.strip().upper() for t in args.tickers.split(",")]
    strategy = {"universe": universe, "threshold_pct": args.threshold}
    result = scan_levels(strategy)

    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
