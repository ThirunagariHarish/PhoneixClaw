"""Train LightGBM classifier for trade prediction."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    X_train = np.load(data_dir / "X_train.npy")
    X_val = np.load(data_dir / "X_val.npy")
    X_test = np.load(data_dir / "X_test.npy")
    y_train = np.load(data_dir / "y_train.npy")
    y_val = np.load(data_dir / "y_val.npy")
    y_test = np.load(data_dir / "y_test.npy")

    with open(data_dir / "meta.json") as f:
        meta = json.load(f)

    import lightgbm as lgb
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    min_child = min(20, max(1, len(X_train)))
    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=8, learning_rate=0.05,
        num_leaves=63, min_child_samples=min_child,
        subsample=0.8, colsample_bytree=0.8,
        is_unbalance=True, random_state=42, verbose=-1,
    )
    eval_set = [(X_val, y_val)] if len(X_val) > 0 else [(X_train, y_train)]
    model.fit(
        X_train, y_train,
        eval_set=eval_set,
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    results = {
        "model_name": "lightgbm",
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 4) if len(set(y_test)) > 1 else 0.5,
        "artifact_path": str(output_dir / "lightgbm_model.pkl"),
        "feature_importances": dict(zip(
            meta.get("feature_columns", []),
            model.feature_importances_.tolist()
        )) if hasattr(model, "feature_importances_") else {},
    }

    try:
        from compute_trading_metrics import compute_trading_metrics
        results.update(compute_trading_metrics(data_dir, y_prob, threshold=0.55))
    except Exception as exc:
        print(f"  [train_lightgbm] trading metrics computation failed: {exc}")
        results.setdefault("sharpe_ratio", 0.0)
        results.setdefault("max_drawdown_pct", 0.0)
        results.setdefault("profit_factor", 1.0)

    joblib.dump(model, output_dir / "lightgbm_model.pkl")
    with open(output_dir / "lightgbm_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"LightGBM: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}")
    try:
        from report_to_phoenix import report_progress
        report_progress("train_lightgbm", "LightGBM training complete", 47)
    except Exception:
        pass


if __name__ == "__main__":
    main()
