"""T2: PnL magnitude regressors.

Trains two LightGBM regressors on the win/loss subsets so the decision engine
can compute expected value at inference time:

    pnl_win_model.pkl   — E[pnl_pct | win]   trained on y_win == 1
    pnl_loss_model.pkl  — E[pnl_pct | loss]  trained on y_win == 0
    ev_threshold.json   — manifest-configured EV gate threshold (default 0)

Both heads read X_*/y_pnl_*/y_*.npy from the preprocess output dir.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np


def _fit_subset(X_train, y_pnl_train, y_win_train, label_value, X_val, y_pnl_val, y_win_val):
    mask_tr = (y_win_train == label_value) & np.isfinite(y_pnl_train)
    if mask_tr.sum() < 20:
        return None, {"skipped": True, "reason": f"only {int(mask_tr.sum())} rows"}

    try:
        import lightgbm as lgb
    except ImportError:
        return None, {"error": "lightgbm not installed"}

    model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    eval_set = None
    if len(X_val) > 0:
        mask_va = (y_win_val == label_value) & np.isfinite(y_pnl_val)
        if mask_va.any():
            eval_set = [(X_val[mask_va], y_pnl_val[mask_va])]

    fit_kwargs = {}
    if eval_set:
        fit_kwargs["eval_set"] = eval_set
        fit_kwargs["callbacks"] = [lgb.early_stopping(50, verbose=False)]
    model.fit(X_train[mask_tr], y_pnl_train[mask_tr], **fit_kwargs)

    preds = model.predict(X_train[mask_tr])
    metrics = {
        "n_train": int(mask_tr.sum()),
        "train_mean_pred": float(np.mean(preds)),
        "train_mean_actual": float(np.mean(y_pnl_train[mask_tr])),
    }
    return model, metrics


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ev-threshold", type=float, default=0.0,
                   help="Default EV gate threshold (decimal PnL units)")
    args = p.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    X_train = np.load(data_dir / "X_train.npy")
    X_val = np.load(data_dir / "X_val.npy")
    y_pnl_train = np.load(data_dir / "y_pnl_train.npy")
    y_pnl_val = np.load(data_dir / "y_pnl_val.npy") if (data_dir / "y_pnl_val.npy").exists() else np.array([])
    y_win_train = np.load(data_dir / "y_train.npy")
    y_win_val = np.load(data_dir / "y_val.npy") if (data_dir / "y_val.npy").exists() else np.array([])

    win_model, win_metrics = _fit_subset(
        X_train, y_pnl_train, y_win_train, 1, X_val, y_pnl_val, y_win_val
    )
    loss_model, loss_metrics = _fit_subset(
        X_train, y_pnl_train, y_win_train, 0, X_val, y_pnl_val, y_win_val
    )

    result = {
        "head": "pnl_regressor",
        "ev_threshold": args.ev_threshold,
        "win": win_metrics,
        "loss": loss_metrics,
    }
    if win_model is not None:
        joblib.dump(win_model, out_dir / "pnl_win_model.pkl")
    if loss_model is not None:
        joblib.dump(loss_model, out_dir / "pnl_loss_model.pkl")

    with open(out_dir / "ev_threshold.json", "w") as f:
        json.dump({"ev_threshold": args.ev_threshold}, f)

    print(json.dumps(result, indent=2, default=str))

    try:
        from report_to_phoenix import report_progress
        report_progress("train_pnl_regressor", "PnL regressors trained", 60, result)
    except Exception:
        pass


if __name__ == "__main__":
    main()
