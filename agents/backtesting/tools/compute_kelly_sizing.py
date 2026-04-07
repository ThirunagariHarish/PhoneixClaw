"""T7: Walk-forward calibrator for fractional Kelly sizing.

Sweeps kelly_fraction ∈ {0.1, 0.2, 0.25, 0.33, 0.5} over the walk-forward
test-set equity curve and picks the one that maximizes Sharpe while keeping
max-DD below a configurable cap. Writes `kelly.json` for trade_intelligence.py.

Usage:
    python tools/compute_kelly_sizing.py --data output/ --output output/models/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


KELLY_GRID = [0.10, 0.20, 0.25, 0.33, 0.50]
MAX_DD_CAP = 0.15  # 15%


def _equity_curve(returns: np.ndarray) -> np.ndarray:
    return np.cumprod(1.0 + returns)


def _metrics(returns: np.ndarray) -> dict:
    if len(returns) == 0:
        return {"sharpe": 0.0, "max_dd": 0.0, "total_return": 0.0}
    mean = float(np.mean(returns))
    std = float(np.std(returns)) or 1e-9
    sharpe = (mean / std) * np.sqrt(252.0)
    equity = _equity_curve(returns)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(abs(np.min(drawdown)))
    total_return = float(equity[-1] - 1.0)
    return {"sharpe": float(sharpe), "max_dd": max_dd, "total_return": total_return}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--max-dd-cap", type=float, default=MAX_DD_CAP)
    args = p.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Need test-set win probabilities + actual PnL
    y_pnl_path = data_dir / "y_pnl_test.npy"
    y_test_path = data_dir / "y_test.npy"
    if not y_pnl_path.exists() or not y_test_path.exists():
        result = {"status": "skipped", "reason": "missing y_pnl_test or y_test"}
        with open(out_dir / "kelly.json", "w") as f:
            json.dump({"kelly_fraction": 0.25, "calibration": result}, f, indent=2)
        print(json.dumps(result))
        return

    y_pnl = np.load(y_pnl_path).astype(float)
    y_win = np.load(y_test_path).astype(int)
    mask = np.isfinite(y_pnl)
    y_pnl = y_pnl[mask]
    y_win = y_win[mask]
    if len(y_pnl) < 20:
        result = {"status": "skipped", "reason": f"only {len(y_pnl)} test rows"}
        with open(out_dir / "kelly.json", "w") as f:
            json.dump({"kelly_fraction": 0.25, "calibration": result}, f, indent=2)
        return

    # Empirical edge + variance from test set
    wins = y_pnl[y_win == 1]
    losses = y_pnl[y_win == 0]
    if len(wins) == 0 or len(losses) == 0:
        result = {"status": "skipped", "reason": "no wins or no losses in test set"}
        with open(out_dir / "kelly.json", "w") as f:
            json.dump({"kelly_fraction": 0.25, "calibration": result}, f, indent=2)
        return

    p_win = len(wins) / len(y_pnl)
    e_win = float(np.mean(wins))
    e_loss = float(np.mean(losses))
    edge = p_win * e_win + (1 - p_win) * e_loss
    variance = p_win * e_win ** 2 + (1 - p_win) * e_loss ** 2 - edge ** 2

    if variance <= 1e-9 or edge <= 0:
        result = {"status": "fallback", "reason": "no positive edge", "p_win": p_win}
        with open(out_dir / "kelly.json", "w") as f:
            json.dump({"kelly_fraction": 0.10, "calibration": result}, f, indent=2)
        return

    full_kelly = edge / variance

    # Sweep kelly fractions
    sweep = []
    best = None
    for k in KELLY_GRID:
        scaled_returns = y_pnl * (k * full_kelly)
        m = _metrics(scaled_returns)
        m["kelly_fraction"] = k
        sweep.append(m)
        # Pick highest Sharpe under DD cap
        if m["max_dd"] <= args.max_dd_cap:
            if best is None or m["sharpe"] > best["sharpe"]:
                best = m

    if best is None:
        best = min(sweep, key=lambda m: m["max_dd"])  # pick least-painful option

    payload = {
        "kelly_fraction": best["kelly_fraction"],
        "full_kelly": float(full_kelly),
        "p_win": float(p_win),
        "e_win": e_win,
        "e_loss": e_loss,
        "selected_metrics": best,
        "sweep": sweep,
    }
    with open(out_dir / "kelly.json", "w") as f:
        json.dump(payload, f, indent=2)

    print(json.dumps(payload, indent=2))
    try:
        from report_to_phoenix import report_progress
        report_progress("compute_kelly", f"kelly_fraction={best['kelly_fraction']}", 62, payload)
    except Exception:
        pass


if __name__ == "__main__":
    main()
