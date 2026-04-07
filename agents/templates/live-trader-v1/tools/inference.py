"""Run trained classifier on a new trade signal."""

import argparse
import json
import logging
from pathlib import Path

import joblib
import pandas as pd

log = logging.getLogger(__name__)

# Reliable sklearn/lgbm fallback model names (in preference order)
_PKL_FALLBACK_NAMES = ["lightgbm", "lgbm", "xgboost", "rf", "random_forest", "logistic"]


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
    pkl_path = models / f"{model_name}_model.pkl"
    pt_path = models / f"{model_name}_model.pt"

    model = None
    used_model_name = model_name

    if pkl_path.exists():
        # Primary: load the sklearn/joblib .pkl model
        model = joblib.load(pkl_path)
        log.info("[inference] Loaded primary model: %s", pkl_path)

    elif pt_path.exists():
        # PyTorch model found but we cannot load it without the class definition.
        # Fall back to the best available .pkl model instead.
        log.warning(
            "[inference] Best model '%s' is a PyTorch .pt file — cannot load without class. "
            "Searching for sklearn/lgbm fallback...",
            model_name,
        )
        # Search fallbacks in preference order, then scan for any .pkl in models dir.
        fallback_candidates = [
            models / f"{name}_model.pkl" for name in _PKL_FALLBACK_NAMES
        ] + sorted(models.glob("*_model.pkl"))

        for candidate in fallback_candidates:
            if candidate.exists():
                used_model_name = candidate.stem.replace("_model", "")
                model = joblib.load(candidate)
                log.warning(
                    "[inference] Using fallback model '%s' instead of PyTorch '%s'",
                    used_model_name,
                    model_name,
                )
                break

        if model is None:
            raise FileNotFoundError(
                f"Best model '{model_name}' is a PyTorch .pt file and no sklearn/lgbm "
                f"fallback .pkl was found in '{models_dir}'. "
                "Retrain with a tree-based model or provide a fallback."
            )

    else:
        # Neither .pkl nor .pt exists — scan for any available model.
        available_pkls = sorted(models.glob("*_model.pkl"))
        if available_pkls:
            candidate = available_pkls[0]
            used_model_name = candidate.stem.replace("_model", "")
            model = joblib.load(candidate)
            log.warning(
                "[inference] Model '%s' not found; using first available: '%s'",
                model_name,
                used_model_name,
            )
        else:
            raise FileNotFoundError(
                f"No model files found in '{models_dir}'. "
                f"Expected '{pkl_path}' (.pkl) or '{pt_path}' (.pt). "
                "Run backtesting to generate a trained model before launching live trading."
            )

    prediction = int(model.predict(features_scaled)[0])
    confidence = (
        float(model.predict_proba(features_scaled)[0][1])
        if hasattr(model, "predict_proba")
        else float(prediction)
    )

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
        "model": used_model_name,
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

    print(
        f"Prediction: {result['prediction']} "
        f"(confidence={result['confidence']}, patterns={result['pattern_matches']})"
    )


if __name__ == "__main__":
    main()
