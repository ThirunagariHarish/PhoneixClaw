"""EMA crossover detection — specialized for TQQ/SQQQ rebalancing strategies.

Usage:
    python ema_crossover.py --underlying QQQ --bull TQQ --bear SQQQ --fast 8 --slow 24
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def check_crossover(strategy: dict) -> dict:
    """Detect EMA crossover for a strategy config."""
    try:
        import yfinance as yf
    except ImportError:
        return {"signal": None, "reason": "yfinance not installed"}

    instruments = strategy.get("instruments", {})
    bull = instruments.get("bull", "TQQ")
    bear = instruments.get("bear", "SQQQ")
    underlying = strategy.get("underlying", "QQQ")
    fast = int(strategy.get("fast_ema", 8))
    slow = int(strategy.get("slow_ema", 24))

    try:
        data = yf.download(underlying, period="60d", progress=False)
        if data.empty or len(data) < slow + 5:
            return {"signal": None, "reason": f"Insufficient data for {underlying}"}
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()

        cur_f = float(ema_fast.iloc[-1])
        cur_s = float(ema_slow.iloc[-1])
        prev_f = float(ema_fast.iloc[-2])
        prev_s = float(ema_slow.iloc[-2])

        # Compute today's separation as confidence proxy
        separation_pct = abs(cur_f - cur_s) / cur_s * 100 if cur_s > 0 else 0

        if prev_f <= prev_s and cur_f > cur_s:
            return {
                "signal": "BUY",
                "ticker": bull,
                "direction": "buy",
                "rotate_out": bear,
                "confidence": min(0.6 + separation_pct / 10, 0.95),
                "reason": f"EMA{fast} crossed above EMA{slow} on {underlying}",
                "underlying": underlying,
                "ema_fast": round(cur_f, 4),
                "ema_slow": round(cur_s, 4),
                "separation_pct": round(separation_pct, 2),
                "strategy_type": "ema_crossover",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if prev_f >= prev_s and cur_f < cur_s:
            return {
                "signal": "BUY",
                "ticker": bear,
                "direction": "buy",
                "rotate_out": bull,
                "confidence": min(0.6 + separation_pct / 10, 0.95),
                "reason": f"EMA{fast} crossed below EMA{slow} on {underlying}",
                "underlying": underlying,
                "ema_fast": round(cur_f, 4),
                "ema_slow": round(cur_s, 4),
                "separation_pct": round(separation_pct, 2),
                "strategy_type": "ema_crossover",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return {
            "signal": None,
            "reason": (f"No crossover; EMA{fast}={cur_f:.2f} EMA{slow}={cur_s:.2f} "
                       f"({'above' if cur_f > cur_s else 'below'})"),
            "current_state": "bullish" if cur_f > cur_s else "bearish",
            "ema_fast": round(cur_f, 4),
            "ema_slow": round(cur_s, 4),
        }

    except Exception as e:
        return {"signal": None, "reason": f"Error: {str(e)[:200]}"}


def main():
    parser = argparse.ArgumentParser(description="EMA crossover detector")
    parser.add_argument("--underlying", default="QQQ")
    parser.add_argument("--bull", default="TQQ")
    parser.add_argument("--bear", default="SQQQ")
    parser.add_argument("--fast", type=int, default=8)
    parser.add_argument("--slow", type=int, default=24)
    parser.add_argument("--output", default="ema_signal.json")
    args = parser.parse_args()

    strategy = {
        "underlying": args.underlying,
        "instruments": {"bull": args.bull, "bear": args.bear},
        "fast_ema": args.fast,
        "slow_ema": args.slow,
    }

    result = check_crossover(strategy)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
