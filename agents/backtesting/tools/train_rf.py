"""Train Random Forest classifier for trade prediction."""

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
    X_test = np.load(data_dir / "X_test.npy")
    y_train = np.load(data_dir / "y_train.npy")
    y_test = np.load(data_dir / "y_test.npy")

    with open(data_dir / "meta.json") as f:
        meta = json.load(f)

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    model = RandomForestClassifier(
        n_estimators=500, max_depth=12, min_samples_leaf=10,
        class_weight="balanced", n_jobs=-1, random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    results = {
        "model_name": "random_forest",
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 4) if len(set(y_test)) > 1 else 0.5,
        "profit_factor": 1.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "artifact_path": str(output_dir / "rf_model.pkl"),
        "feature_importances": dict(zip(
            meta.get("feature_columns", []),
            model.feature_importances_.tolist()
        )),
    }

    joblib.dump(model, output_dir / "rf_model.pkl")
    with open(output_dir / "rf_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Random Forest: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}")


if __name__ == "__main__":
    main()
