"""T5: Entry-buffer + fillability models.

Two heads:
    entry_buffer_model.pkl  — LightGBM regressor on y_entry_slip_bps
    fillability_model.pkl   — LightGBM classifier on y_fill_60s

Both labels are populated by the live execution feedback loop (order_attempts
table + T11 feedback). Until enough live data exists, this script skips cleanly
and decision_engine falls back to compute_price_buffer.json priors.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np


def _train_reg(X_train, y_train, X_val, y_val):
    mask = np.isfinite(y_train)
    if mask.sum() < 30:
        return None, {"skipped": True, "reason": f"only {int(mask.sum())} labels"}
    try:
        import lightgbm as lgb
    except ImportError:
        return None, {"error": "lightgbm not installed"}
    model = lgb.LGBMRegressor(
        objective="regression", n_estimators=300, max_depth=6,
        learning_rate=0.05, random_state=42, verbose=-1,
    )
    fit_kwargs = {}
    if len(X_val) > 0:
        mv = np.isfinite(y_val)
        if mv.any():
            fit_kwargs["eval_set"] = [(X_val[mv], y_val[mv])]
            fit_kwargs["callbacks"] = [lgb.early_stopping(50, verbose=False)]
    model.fit(X_train[mask], y_train[mask], **fit_kwargs)
    return model, {"n_train": int(mask.sum())}


def _train_cls(X_train, y_train, X_val, y_val):
    mask = np.isfinite(y_train)
    if mask.sum() < 30:
        return None, {"skipped": True, "reason": f"only {int(mask.sum())} labels"}
    try:
        import lightgbm as lgb
    except ImportError:
        return None, {"error": "lightgbm not installed"}
    y_bin = y_train[mask].astype(int)
    if len(np.unique(y_bin)) < 2:
        return None, {"skipped": True, "reason": "only one class present"}
    model = lgb.LGBMClassifier(
        objective="binary", n_estimators=300, max_depth=6,
        learning_rate=0.05, random_state=42, verbose=-1,
    )
    fit_kwargs = {}
    if len(X_val) > 0:
        mv = np.isfinite(y_val)
        if mv.any():
            fit_kwargs["eval_set"] = [(X_val[mv], y_val[mv].astype(int))]
            fit_kwargs["callbacks"] = [lgb.early_stopping(50, verbose=False)]
    model.fit(X_train[mask], y_bin, **fit_kwargs)
    return model, {"n_train": int(mask.sum())}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    data_dir = Path(args.data)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    X_train = np.load(data_dir / "X_train.npy")
    X_val = np.load(data_dir / "X_val.npy")

    result: dict = {"head": "entry_buffer_fillability"}

    slip_path = data_dir / "y_slip_train.npy"
    if slip_path.exists():
        y_tr = np.load(slip_path)
        y_va = np.load(data_dir / "y_slip_val.npy") if (data_dir / "y_slip_val.npy").exists() else np.array([])
        mdl, meta = _train_reg(X_train, y_tr, X_val, y_va)
        if mdl is not None:
            joblib.dump(mdl, out_dir / "entry_buffer_model.pkl")
        result["slippage_regressor"] = meta
    else:
        result["slippage_regressor"] = {"skipped": True, "reason": "no y_slip labels yet"}

    fill_path = data_dir / "y_fill_train.npy"
    if fill_path.exists():
        y_tr = np.load(fill_path)
        y_va = np.load(data_dir / "y_fill_val.npy") if (data_dir / "y_fill_val.npy").exists() else np.array([])
        mdl, meta = _train_cls(X_train, y_tr, X_val, y_va)
        if mdl is not None:
            joblib.dump(mdl, out_dir / "fillability_model.pkl")
        result["fillability_classifier"] = meta
    else:
        result["fillability_classifier"] = {"skipped": True, "reason": "no y_fill labels yet"}

    print(json.dumps(result, indent=2))
    try:
        from report_to_phoenix import report_progress
        report_progress("train_entry_buffer", "Entry buffer heads", 64, result)
    except Exception:
        pass


if __name__ == "__main__":
    main()
