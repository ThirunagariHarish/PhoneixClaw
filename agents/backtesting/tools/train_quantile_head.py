"""Shared LightGBM quantile-regressor trainer used by T3 (SL/TP) and similar heads.

Usage (invoked by train_stop_loss_model.py / train_profit_target_model.py):
    python tools/train_quantile_head.py \
        --data output/ \
        --output output/models/ \
        --head sl   # or tp
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np


HEAD_CONFIG = {
    "sl": {
        "label_stem": "y_mae_atr",
        "alpha": 0.25,
        "model_filename": "stop_loss_model.pkl",
        "meta_filename": "stop_loss_model.json",
        "description": "Quantile regressor (alpha=0.25) on MAE/ATR14 — conservative SL multiple",
    },
    "tp": {
        "label_stem": "y_mfe_atr",
        "alpha": 0.75,
        "model_filename": "profit_target_model.pkl",
        "meta_filename": "profit_target_model.json",
        "description": "Quantile regressor (alpha=0.75) on MFE/ATR14 — ambitious TP multiple",
    },
}


def _load_split(data_dir: Path, stem: str):
    tr = data_dir / f"{stem}_train.npy"
    va = data_dir / f"{stem}_val.npy"
    te = data_dir / f"{stem}_test.npy"
    if not tr.exists():
        return None, None, None
    return np.load(tr), np.load(va) if va.exists() else np.array([]), np.load(te) if te.exists() else np.array([])


def train_quantile(data_dir: Path, output_dir: Path, head: str) -> dict:
    cfg = HEAD_CONFIG[head]
    X_train = np.load(data_dir / "X_train.npy")
    X_val = np.load(data_dir / "X_val.npy")
    X_test = np.load(data_dir / "X_test.npy")

    y_train, y_val, y_test = _load_split(data_dir, cfg["label_stem"])
    if y_train is None:
        return {"status": "skipped", "reason": f"missing {cfg['label_stem']}_*.npy — run compute_labels first"}

    # Mask NaN targets out of training
    mask_tr = np.isfinite(y_train)
    if mask_tr.sum() < 20:
        return {"status": "skipped", "reason": f"only {int(mask_tr.sum())} valid labels — need >=20"}
    X_train, y_train = X_train[mask_tr], y_train[mask_tr]

    mask_va = np.isfinite(y_val) if len(y_val) else np.array([], dtype=bool)
    if mask_va.any():
        X_val, y_val = X_val[mask_va], y_val[mask_va]
    mask_te = np.isfinite(y_test) if len(y_test) else np.array([], dtype=bool)
    if mask_te.any():
        X_test_f, y_test_f = X_test[mask_te], y_test[mask_te]
    else:
        X_test_f, y_test_f = X_test[:0], np.array([])

    try:
        import lightgbm as lgb
    except ImportError:
        return {"status": "error", "reason": "lightgbm not installed"}

    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=cfg["alpha"],
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    eval_set = [(X_val, y_val)] if len(X_val) > 0 else None
    fit_kwargs = {}
    if eval_set:
        fit_kwargs["eval_set"] = eval_set
        fit_kwargs["callbacks"] = [lgb.early_stopping(50, verbose=False)]
    model.fit(X_train, y_train, **fit_kwargs)

    metrics: dict = {"alpha": cfg["alpha"]}
    if len(X_test_f) > 0:
        preds = model.predict(X_test_f)
        residuals = y_test_f - preds
        metrics["test_mae"] = float(np.mean(np.abs(residuals)))
        # Empirical quantile coverage — should be near alpha
        metrics["empirical_quantile"] = float(np.mean(preds >= y_test_f))
        metrics["test_samples"] = int(len(y_test_f))

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / cfg["model_filename"]
    joblib.dump(model, model_path)

    meta = {
        "head": head,
        "label": cfg["label_stem"],
        "description": cfg["description"],
        "model_path": str(model_path),
        "alpha": cfg["alpha"],
        "metrics": metrics,
        "n_train": int(len(y_train)),
    }
    with open(output_dir / cfg["meta_filename"], "w") as f:
        json.dump(meta, f, indent=2)
    return {"status": "ok", **meta}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--head", required=True, choices=["sl", "tp"])
    args = p.parse_args()
    result = train_quantile(Path(args.data), Path(args.output), args.head)
    print(json.dumps(result, indent=2, default=str))
    try:
        from report_to_phoenix import report_progress
        report_progress(
            f"train_{args.head}",
            f"{args.head.upper()} quantile head: {result.get('status')}",
            58,
            {f"{args.head}_head": result},
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
