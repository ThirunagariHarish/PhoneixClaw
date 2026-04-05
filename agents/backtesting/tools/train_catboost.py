"""Train CatBoost classifier with native categorical feature handling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def _load_feature_names(data_dir: Path) -> list[str] | None:
    fn_path = data_dir / "feature_names.json"
    if fn_path.exists():
        with open(fn_path) as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return [str(x) for x in raw]
        if isinstance(raw, dict) and "features" in raw:
            return [str(x) for x in raw["features"]]
    meta_path = data_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        cols = meta.get("feature_columns")
        if cols:
            return [str(x) for x in cols]
    return None


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

    tabular_names = _load_feature_names(data_dir)
    if tabular_names is not None and len(tabular_names) != X_train.shape[1]:
        tabular_names = None

    cat_train = np.load(data_dir / "categoricals_train.npy") if (data_dir / "categoricals_train.npy").exists() else None
    cat_val = np.load(data_dir / "categoricals_val.npy") if (data_dir / "categoricals_val.npy").exists() else None
    cat_test = np.load(data_dir / "categoricals_test.npy") if (data_dir / "categoricals_test.npy").exists() else None

    if cat_train is not None:
        X_train_full = np.hstack([X_train, cat_train])
        X_val_full = np.hstack([X_val, cat_val])
        X_test_full = np.hstack([X_test, cat_test])
        cat_feature_indices = list(range(X_train.shape[1], X_train_full.shape[1]))
        n_cat = cat_train.shape[1]
        cat_names = [f"cat_{j}" for j in range(n_cat)]
        if tabular_names is not None:
            feature_names = tabular_names + cat_names
        else:
            feature_names = [f"f{i}" for i in range(X_train.shape[1])] + cat_names
    else:
        X_train_full = X_train
        X_val_full = X_val
        X_test_full = X_test
        cat_feature_indices = []
        feature_names = tabular_names if tabular_names is not None else [f"f{i}" for i in range(X_train.shape[1])]

    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError:
        print("CatBoost not available, skipping")
        results = {"model_name": "catboost", "accuracy": 0, "error": "catboost not installed"}
        with open(output_dir / "catboost_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    model = CatBoostClassifier(
        iterations=1000,
        depth=8,
        learning_rate=0.03,
        cat_features=cat_feature_indices if cat_feature_indices else None,
        auto_class_weights="Balanced",
        eval_metric="AUC",
        early_stopping_rounds=50,
        verbose=100,
    )

    cat_kw = cat_feature_indices if cat_feature_indices else None
    train_pool = Pool(
        data=X_train_full,
        label=y_train,
        cat_features=cat_kw,
        feature_names=feature_names,
    )
    if len(X_val_full) > 0:
        val_pool = Pool(
            data=X_val_full,
            label=y_val,
            cat_features=cat_kw,
            feature_names=feature_names,
        )
        model.fit(train_pool, eval_set=val_pool)
    else:
        model.fit(train_pool, eval_set=train_pool)
    model.save_model(str(output_dir / "catboost_model.cbm"))

    test_pool = Pool(
        data=X_test_full,
        cat_features=cat_kw,
        feature_names=feature_names,
    )
    y_prob = model.predict_proba(test_pool)[:, 1]
    y_pred = (y_prob > 0.5).astype(int)

    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    results = {
        "model_name": "catboost",
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 4) if len(set(y_test)) > 1 else 0.5,
        "profit_factor": 1.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "artifact_path": str(output_dir / "catboost_model.cbm"),
    }
    with open(output_dir / "catboost_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"CatBoost: accuracy={results['accuracy']} auc={results['auc_roc']}")


if __name__ == "__main__":
    main()
