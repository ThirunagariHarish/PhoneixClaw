"""Run trained classifier on a new trade signal."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def predict(features_path: str, models_dir: str = "models") -> dict:
    models = Path(models_dir)

    with open(models / "best_model.json") as f:
        best_info = json.load(f)

    with open(models / "meta.json") as f:
        meta = json.load(f)

    with open(features_path) as f:
        raw_features = json.load(f)

    feature_cols = meta["feature_columns"]
    row = {col: raw_features.get(col, 0.0) for col in feature_cols}
    df = pd.DataFrame([row])

    imputer = joblib.load(models / "imputer.pkl")
    scaler = joblib.load(models / "scaler.pkl")

    df_imp = pd.DataFrame(imputer.transform(df), columns=feature_cols)
    features_scaled = scaler.transform(df_imp)

    model_name = best_info["best_model"]
    model_path = models / f"{model_name}_model.pkl"

    if model_path.exists():
        model = joblib.load(model_path)
        prediction = int(model.predict(features_scaled)[0])
        confidence = float(model.predict_proba(features_scaled)[0][1]) if hasattr(model, "predict_proba") else float(prediction)
    else:
        prediction = 0
        confidence = 0.0

    # Pattern matching
    patterns = []
    patterns_path = models / "patterns.json"
    if patterns_path.exists():
        with open(patterns_path) as f:
            all_patterns = json.load(f)
        for p in all_patterns:
            try:
                if _eval_condition(p["condition"], raw_features):
                    patterns.append({"name": p["name"], "win_rate": p["win_rate"]})
            except Exception:
                pass

    return {
        "prediction": "TRADE" if prediction == 1 else "SKIP",
        "confidence": round(confidence, 4),
        "model": model_name,
        "pattern_matches": len(patterns),
        "patterns": patterns[:10],
    }


def _eval_condition(condition: str, features: dict) -> bool:
    if " == " in condition:
        key, val = condition.split(" == ", 1)
        key = key.strip()
        return str(features.get(key)) == val.strip()
    if " between " in condition:
        parts = condition.split(" between ", 1)
        key = parts[0].strip()
        lo, hi = parts[1].split(" and ")
        val = features.get(key, 0)
        return float(lo) <= float(val) < float(hi)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--models", default="models")
    parser.add_argument("--output", default="prediction.json")
    args = parser.parse_args()

    result = predict(args.features, args.models)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Prediction: {result['prediction']} (confidence={result['confidence']}, patterns={result['pattern_matches']})")


if __name__ == "__main__":
    main()
