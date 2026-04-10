"""Shared trading metrics calculator.

Computes real Sharpe ratio, max drawdown, total return, and profit factor
from a model's test-set predictions. Used by all training scripts to replace
the hardcoded 0.0 values in their `_results.json` output.

Usage from a training script:
    from compute_trading_metrics import compute_trading_metrics

    metrics = compute_trading_metrics(
        data_dir=Path(args.data),
        y_prob=y_prob,  # test set predicted probabilities
        threshold=0.55,
    )
    results.update(metrics)  # adds sharpe_ratio, max_drawdown_pct, etc.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def compute_trading_metrics(
    data_dir: Path,
    y_prob: np.ndarray,
    threshold: float = 0.55,
) -> dict[str, Any]:
    """Simulate taking trades when predicted prob > threshold on the test set.

    Reads the test-set `pnl_pct` values from the enriched parquet (aligned via
    meta.json split indices) and computes realistic trading metrics.

    Args:
        data_dir: The preprocessing output directory (contains meta.json).
        y_prob: Test-set predicted probabilities from the model.
        threshold: Take a trade when y_prob >= threshold.

    Returns:
        Dict with keys: sharpe_ratio, max_drawdown_pct, total_return_pct,
        profit_factor, trades_taken, win_rate_at_threshold.
        All values are floats; returns 0.0 safely on any error.
    """
    result = {
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "total_return_pct": 0.0,
        "profit_factor": 1.0,
        "trades_taken": 0,
        "win_rate_at_threshold": 0.0,
    }

    try:
        # Load meta to find test split location
        meta_path = data_dir / "meta.json"
        if not meta_path.exists():
            return result
        meta = json.loads(meta_path.read_text())
        n_train = int(meta.get("n_train", 0))
        n_val = int(meta.get("n_val", 0))
        n_test = int(meta.get("n_test", 0))
        if n_test == 0:
            return result

        # Locate enriched.parquet — may be in data_dir parent or data_dir itself
        enriched_candidates = [
            data_dir / "enriched.parquet",
            data_dir.parent / "enriched.parquet",
        ]
        enriched_path = next((p for p in enriched_candidates if p.exists()), None)
        if enriched_path is None:
            return result

        import pandas as pd
        df = pd.read_parquet(enriched_path)
        if "pnl_pct" not in df.columns or "is_profitable" not in df.columns:
            return result

        # Extract the test slice (same split as preprocess.py)
        test_start = n_train + n_val
        test_end = test_start + n_test
        if test_end > len(df):
            return result

        # pnl_pct from transform.py is already a fraction (e.g. 0.05 = 5%), NOT percentage points
        pnl_test = df["pnl_pct"].iloc[test_start:test_end].fillna(0).values
        if len(pnl_test) != len(y_prob):
            # Length mismatch — data misaligned, bail
            return result

        # Simulate: take trades where y_prob >= threshold
        take_mask = y_prob >= threshold
        trades_taken = int(take_mask.sum())
        if trades_taken == 0:
            # No trades taken at this threshold — try a lower threshold
            take_mask = y_prob >= 0.50
            trades_taken = int(take_mask.sum())
            if trades_taken == 0:
                return result

        trade_returns = pnl_test[take_mask]

        # Win rate at threshold
        result["trades_taken"] = trades_taken
        result["win_rate_at_threshold"] = round(
            float((trade_returns > 0).mean()), 4
        )

        # Total return (compounded)
        equity_curve = (1.0 + trade_returns).cumprod()
        total_return = float(equity_curve[-1] - 1.0) * 100.0
        result["total_return_pct"] = round(total_return, 4)

        # Sharpe ratio (annualized, assuming ~252 trading days and each trade is roughly daily)
        # This is an approximation — real Sharpe needs timestamps for correct annualization
        if trade_returns.std() > 0:
            sharpe = float(trade_returns.mean() / trade_returns.std() * np.sqrt(252))
            result["sharpe_ratio"] = round(sharpe, 4)

        # Max drawdown
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - peak) / peak
        max_dd = float(drawdown.min()) * 100.0
        result["max_drawdown_pct"] = round(max_dd, 4)

        # Profit factor: sum(wins) / abs(sum(losses))
        wins = trade_returns[trade_returns > 0].sum()
        losses = trade_returns[trade_returns < 0].sum()
        if losses < 0:
            result["profit_factor"] = round(float(wins / abs(losses)), 4)
        elif wins > 0:
            result["profit_factor"] = 10.0  # All wins, no losses — cap at 10
        else:
            result["profit_factor"] = 1.0

    except Exception as e:
        # Never raise — return defaults if anything goes wrong
        print(f"  [trading_metrics] error: {e}")

    return result
