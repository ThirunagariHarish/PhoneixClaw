"""T10: Per-regime logistic recalibration for the entry classifier.

Fits a lightweight 1D logistic regression per market regime on top of the
frozen base-model probabilities, producing `regime_calibration.json`:

    {
        "bull_quiet":    {"intercept": -0.12, "slope": 1.08},
        "bear_volatile": {"intercept":  0.22, "slope": 0.81},
        ...
    }

At inference time trade_intelligence.apply_regime_calibration reads this file
and remaps raw model confidence through the matching regime's sigmoid.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


REGIMES = ["bull_quiet", "bull_volatile", "bear_quiet", "bear_volatile", "choppy"]


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> dict | None:
    if len(x) < 30 or len(np.unique(y)) < 2:
        return None
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        return None
    # Use the raw confidence as a single feature
    X = x.reshape(-1, 1)
    clf = LogisticRegression(max_iter=200)
    clf.fit(X, y)
    return {
        "intercept": float(clf.intercept_[0]),
        "slope": float(clf.coef_[0][0]),
        "n_samples": int(len(x)),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--enriched", required=True,
                   help="Enriched parquet with regime column")
    p.add_argument("--predictions", required=True,
                   help="NPY of base-model probabilities aligned to enriched rows")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    enriched = pd.read_parquet(args.enriched)
    try:
        probs = np.load(args.predictions)
    except (ValueError, OSError, FileNotFoundError) as e:
        # Predictions file unavailable or wrong format (orchestrator may pass a
        # JSON path here when no aligned-probabilities artifact exists yet).
        # Don't crash the pipeline — write empty calibration and exit cleanly.
        with open(args.output, "w") as f:
            json.dump({}, f)
        print(f"compute_regime_calibration: skipping ({type(e).__name__}: {e})")
        return
    if len(probs) != len(enriched):
        print(f"ERROR: probs len {len(probs)} != enriched len {len(enriched)}")
        with open(args.output, "w") as f:
            json.dump({}, f)
        return

    regime_col = None
    for col in ("market_regime", "regime"):
        if col in enriched.columns:
            regime_col = col
            break
    if regime_col is None:
        with open(args.output, "w") as f:
            json.dump({}, f)
        print("No regime column — wrote empty calibration")
        return

    y = enriched["is_profitable"].astype(int).values if "is_profitable" in enriched else (probs > 0.5).astype(int)

    result: dict = {}
    for regime in REGIMES:
        mask = enriched[regime_col] == regime
        cal = _fit_logistic(probs[mask], y[mask])
        if cal is not None:
            result[regime] = cal

    # Fallback: global calibration
    if "global" not in result:
        cal = _fit_logistic(probs, y)
        if cal is not None:
            result["__global__"] = cal

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))

    try:
        from report_to_phoenix import report_progress
        report_progress("regime_calibration", "Regime calibration fitted", 66, {"regimes_fitted": list(result.keys())})
    except Exception:
        pass


if __name__ == "__main__":
    main()
