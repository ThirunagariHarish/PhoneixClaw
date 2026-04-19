"""Run trained classifier on a new trade signal."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import joblib
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [inference] %(levelname)s %(message)s",
    stream=sys.stderr,
)
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

    result = {
        "prediction": "TRADE" if prediction == 1 else "SKIP",
        "confidence": round(confidence, 4),
        "model": used_model_name,
        "pattern_matches": len(patterns),
        "patterns": patterns[:10],
    }

    correlation_id = raw_features.get("correlation_id") or os.getenv("CORRELATION_ID")
    if correlation_id:
        result["correlation_id"] = correlation_id
        log.info("Inference complete: %s", result["prediction"], extra={"correlation_id": correlation_id})

    return result


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


async def _write_dlq(connector_id: str, payload: dict, error: str) -> None:
    """Write failed signal to dead_letter_messages table."""
    try:
        from sqlalchemy import text

        from shared.db.engine import get_session
        async for session in get_session():
            await session.execute(
                text("INSERT INTO dead_letter_messages (connector_id, payload, error) VALUES (:cid, :payload, :error)"),
                {"cid": connector_id, "payload": json.dumps(payload), "error": error[:500]},
            )
            await session.commit()
            log.warning("DLQ write succeeded for connector %s", connector_id, extra={"correlation_id": payload.get("correlation_id")})
    except Exception as dlq_exc:
        log.error("DLQ write failed: %s", dlq_exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--models", default="models")
    parser.add_argument("--output", default="prediction.json")
    parser.add_argument("--config", help="Path to config.json for connector_id")
    args = parser.parse_args()

    try:
        result = predict(args.features, args.models)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(json.dumps({"status": "ok", "prediction": result["prediction"]}))
    except Exception as exc:
        log.error("inference failed: %s", exc, exc_info=True)
        connector_id = "unknown"
        features_dict = {}
        if args.config and Path(args.config).exists():
            try:
                cfg = json.loads(Path(args.config).read_text())
                connector_id = cfg.get("connector_id", "unknown")
            except Exception:
                pass
        if Path(args.features).exists():
            try:
                with open(args.features) as f:
                    features_dict = json.load(f)
            except Exception:
                pass
        import asyncio
        asyncio.run(_write_dlq(connector_id, features_dict, str(exc)))
        sys.exit(1)

    print(
        f"Prediction: {result['prediction']} "
        f"(confidence={result['confidence']}, patterns={result['pattern_matches']})"
    )


if __name__ == "__main__":
    main()
