"""T4: Exit timing heads.

    exit_timing_model.pkl  — LightGBM regressor on y_hold_minutes
    exit_bucket_model.pkl  — LightGBM multiclass on y_exit_bucket (5 classes)

Labels come from compute_labels.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np


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
    X_test = np.load(data_dir / "X_test.npy")

    result: dict = {"head": "exit_timing"}

    try:
        import lightgbm as lgb
    except ImportError:
        with open(out_dir / "exit_timing.json", "w") as f:
            json.dump({"error": "lightgbm not installed"}, f)
        return

    hold_path = data_dir / "y_hold_train.npy"
    if hold_path.exists():
        y_tr = np.load(hold_path)
        y_va = np.load(data_dir / "y_hold_val.npy") if (data_dir / "y_hold_val.npy").exists() else np.array([])
        mask = np.isfinite(y_tr)
        if mask.sum() >= 20:
            reg = lgb.LGBMRegressor(
                objective="regression", n_estimators=300, max_depth=6,
                learning_rate=0.05, random_state=42, verbose=-1,
            )
            fit_kwargs = {}
            if len(y_va):
                mv = np.isfinite(y_va)
                if mv.any():
                    fit_kwargs["eval_set"] = [(X_val[mv], y_va[mv])]
                    fit_kwargs["callbacks"] = [lgb.early_stopping(50, verbose=False)]
            reg.fit(X_train[mask], y_tr[mask], **fit_kwargs)
            joblib.dump(reg, out_dir / "exit_timing_model.pkl")
            result["hold_regressor"] = {"n_train": int(mask.sum())}
        else:
            result["hold_regressor"] = {"skipped": True}
    else:
        result["hold_regressor"] = {"skipped": True, "reason": "no y_hold labels"}

    bucket_path = data_dir / "y_exit_bucket_train.npy"
    if bucket_path.exists():
        y_tr = np.load(bucket_path)
        y_va = np.load(data_dir / "y_exit_bucket_val.npy") if (data_dir / "y_exit_bucket_val.npy").exists() else np.array([])
        if len(np.unique(y_tr)) >= 2 and len(y_tr) >= 20:
            clf = lgb.LGBMClassifier(
                objective="multiclass", num_class=5,
                n_estimators=300, max_depth=6, learning_rate=0.05,
                random_state=42, verbose=-1,
            )
            fit_kwargs = {}
            if len(y_va):
                fit_kwargs["eval_set"] = [(X_val, y_va)]
                fit_kwargs["callbacks"] = [lgb.early_stopping(50, verbose=False)]
            clf.fit(X_train, y_tr, **fit_kwargs)
            joblib.dump(clf, out_dir / "exit_bucket_model.pkl")
            result["bucket_classifier"] = {"n_train": int(len(y_tr)), "classes": sorted(map(int, np.unique(y_tr).tolist()))}
        else:
            result["bucket_classifier"] = {"skipped": True, "reason": "insufficient class diversity"}
    else:
        result["bucket_classifier"] = {"skipped": True, "reason": "no y_exit_bucket"}

    print(json.dumps(result, indent=2))
    try:
        from report_to_phoenix import report_progress
        report_progress("train_exit_timing", "Exit timing heads", 65, result)
    except Exception:
        pass


if __name__ == "__main__":
    main()
