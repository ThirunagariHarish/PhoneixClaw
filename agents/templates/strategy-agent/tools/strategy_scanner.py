"""Strategy scanner — evaluates strategy entry/exit rules against live market data.

Reads `config.json["strategy"]` (or top-level `manifest.strategy`), evaluates
the rules using yfinance + technical indicators, and writes signal.json.

Usage:
    python strategy_scanner.py --config config.json --output signal.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_strategy(config: dict) -> dict:
    """Find the strategy block in config (supports several locations)."""
    if "strategy" in config:
        return config["strategy"]
    if "manifest" in config and isinstance(config["manifest"], dict):
        return config["manifest"].get("strategy", {})
    return {}


def evaluate(config: dict) -> dict:
    """Evaluate strategy and produce a signal (or no-op)."""
    strategy = _load_strategy(config)
    if not strategy:
        return {"signal": None, "reason": "No strategy configured"}

    # Dispatch on strategy type
    desc = (strategy.get("description") or strategy.get("name") or "").lower()

    # 1. EMA crossover dispatch
    if "ema" in desc and "cross" in desc:
        return _eval_ema_crossover(strategy)

    # 2. 52-week level dispatch
    if "52" in desc and ("low" in desc or "high" in desc):
        return _eval_52w_level(strategy)

    # 3. Generic rule evaluation
    return _eval_generic_rules(strategy)


def _eval_ema_crossover(strategy: dict) -> dict:
    """Evaluate EMA crossover strategy. Returns BUY/SELL/HOLD."""
    try:
        from ema_crossover import check_crossover
    except ImportError:
        # Fallback inline
        return _eval_ema_inline(strategy)
    return check_crossover(strategy)


def _eval_ema_inline(strategy: dict) -> dict:
    """Inline fallback for EMA evaluation."""
    try:
        import yfinance as yf

        instruments = strategy.get("instruments", {})
        bull = instruments.get("bull", "TQQ")
        bear = instruments.get("bear", "SQQQ")
        underlying = strategy.get("underlying", "QQQ")
        fast = strategy.get("fast_ema", 8)
        slow = strategy.get("slow_ema", 24)

        data = yf.download(underlying, period="60d", progress=False)
        if data.empty or len(data) < slow + 5:
            return {"signal": None, "reason": f"Insufficient data for {underlying}"}
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()

        cur_fast = float(ema_fast.iloc[-1])
        cur_slow = float(ema_slow.iloc[-1])
        prev_fast = float(ema_fast.iloc[-2])
        prev_slow = float(ema_slow.iloc[-2])

        # Bullish crossover
        if prev_fast <= prev_slow and cur_fast > cur_slow:
            return {
                "signal": "BUY",
                "ticker": bull,
                "direction": "buy",
                "confidence": 0.80,
                "reason": f"{underlying} EMA{fast} crossed above EMA{slow}: {cur_fast:.2f} > {cur_slow:.2f}",
                "rotate_out": bear,
                "strategy_type": "ema_crossover",
                "underlying": underlying,
                "ema_fast": cur_fast,
                "ema_slow": cur_slow,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        # Bearish crossover
        if prev_fast >= prev_slow and cur_fast < cur_slow:
            return {
                "signal": "BUY",
                "ticker": bear,
                "direction": "buy",
                "confidence": 0.80,
                "reason": f"{underlying} EMA{fast} crossed below EMA{slow}: {cur_fast:.2f} < {cur_slow:.2f}",
                "rotate_out": bull,
                "strategy_type": "ema_crossover",
                "underlying": underlying,
                "ema_fast": cur_fast,
                "ema_slow": cur_slow,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return {"signal": None, "reason": f"No crossover; fast={cur_fast:.2f} slow={cur_slow:.2f}"}
    except Exception as e:
        return {"signal": None, "reason": f"Error: {str(e)[:200]}"}


def _eval_52w_level(strategy: dict) -> dict:
    """Evaluate 52-week level strategy."""
    try:
        from level_scanner import scan_levels
        return scan_levels(strategy)
    except ImportError:
        return {"signal": None, "reason": "level_scanner not available"}


def _eval_generic_rules(strategy: dict) -> dict:
    """Generic rule evaluation (best-effort)."""
    return {"signal": None, "reason": "Generic strategy not yet supported — use ema_crossover or 52w_level"}


def main():
    parser = argparse.ArgumentParser(description="Strategy scanner")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="signal.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text()) if Path(args.config).exists() else {}
    result = evaluate(config)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))

    if result.get("signal"):
        print(f"  Signal: {result['signal']} {result.get('ticker', '')} — {result.get('reason', '')}")
    else:
        print(f"  No signal: {result.get('reason', '')}")


if __name__ == "__main__":
    main()
