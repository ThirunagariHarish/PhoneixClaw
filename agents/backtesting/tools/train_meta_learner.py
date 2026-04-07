"""Train stacking meta-learner combining all base model predictions."""

import argparse
import json
from pathlib import Path

import numpy as np
import joblib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", required=True, help="Directory containing all model result JSONs")
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data)
    models_dir = Path(args.models_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    y_test = np.load(data_dir / "y_test.npy")

    model_names = ["xgboost", "lightgbm", "rf", "catboost", "lstm", "transformer", "tft", "hybrid"]
    predictions = {}

    for name in model_names:
        pred_path = models_dir / f"{name}_test_proba.npy"
        if pred_path.exists():
            predictions[name] = np.load(pred_path)
        else:
            print(f"Warning: {name} predictions not found at {pred_path}, skipping")

    if len(predictions) < 2:
        print("Need at least 2 model predictions for meta-learner")
        results = {"model_name": "meta_learner", "accuracy": 0, "error": "insufficient base models"}
        with open(output_dir / "meta_learner_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    available_models = sorted(predictions.keys())
    X_meta = np.column_stack([predictions[m] for m in available_models])

    # Simple train/test from the test set itself (in practice, use OOF predictions from training)
    n_meta = len(X_meta)
    if n_meta < 2:
        X_meta_train, X_meta_test = X_meta, X_meta
        y_meta_train, y_meta_test = y_test, y_test
    else:
        split = max(1, int(n_meta * 0.5))
        X_meta_train, X_meta_test = X_meta[:split], X_meta[split:]
        y_meta_train, y_meta_test = y_test[:split], y_test[split:]

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    meta_model = LogisticRegression(C=1.0, max_iter=1000)
    meta_model.fit(X_meta_train, y_meta_train)

    joblib.dump(meta_model, output_dir / "meta_learner.pkl")
    with open(output_dir / "meta_learner_models.json", "w") as f:
        json.dump({"models": available_models}, f, indent=2)

    y_prob = meta_model.predict_proba(X_meta_test)[:, 1]
    y_pred = (y_prob > 0.5).astype(int)

    results = {
        "model_name": "meta_learner",
        "base_models": available_models,
        "accuracy": round(float(accuracy_score(y_meta_test, y_pred)), 4),
        "precision": round(float(precision_score(y_meta_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_meta_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_meta_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_meta_test, y_prob)), 4) if len(set(y_meta_test)) > 1 else 0.5,
        "artifact_path": str(output_dir / "meta_learner.pkl"),
        "model_weights": dict(zip(available_models, meta_model.coef_[0].tolist())),
    }
    try:
        from compute_trading_metrics import compute_trading_metrics
        results.update(compute_trading_metrics(
            data_dir, np.asarray(y_prob).reshape(-1), threshold=0.55
        ))
    except Exception as exc:
        print(f"  [train_meta_learner] trading metrics computation failed: {exc}")
        results.setdefault("sharpe_ratio", 0.0)
        results.setdefault("max_drawdown_pct", 0.0)
        results.setdefault("profit_factor", 1.0)
    with open(output_dir / "meta_learner_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"Meta-Learner: accuracy={results['accuracy']} auc={results['auc_roc']}")
    print(f"  Model weights: {results['model_weights']}")
    try:
        from report_to_phoenix import report_progress
        report_progress("train_meta", "Meta-learner training complete", 60)
    except Exception:
        pass


if __name__ == "__main__":
    main()
