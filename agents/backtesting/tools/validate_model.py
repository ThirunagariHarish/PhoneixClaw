"""Post-backtest model validation on the held-out test set.

Loads the best model, runs inference on the test split (never seen during
training), computes classification and trading metrics, and produces a
human-readable validation report with sample trade predictions.

Usage:
    python tools/validate_model.py --data output/ --models output/models/ --output output/validation_report.json
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

PKL_FALLBACK = ["lightgbm", "lgbm", "xgboost", "catboost", "rf", "random_forest"]


def _load_best_model(models_dir: Path) -> tuple:
    """Load the best model; falls back to sklearn-based if best is PyTorch.

    Each model artifact lives in a per-model subdirectory:
    models/<name>/<name>_model.pkl. Search both the flat layout and the
    nested layout so we work with either training-script convention.
    """
    best_info = json.loads((models_dir / "best_model.json").read_text())
    model_name = best_info.get("best_model", "")

    def _candidate_paths(name: str) -> list[Path]:
        return [
            models_dir / f"{name}_model.pkl",
            models_dir / name / f"{name}_model.pkl",
            models_dir / name / f"rf_model.pkl",  # train_rf.py uses rf_model.pkl
        ]

    for path in _candidate_paths(model_name):
        if path.exists():
            return joblib.load(path), model_name

    for fallback in PKL_FALLBACK:
        for path in _candidate_paths(fallback):
            if path.exists():
                print(f"  Best model '{model_name}' is PyTorch, falling back to '{fallback}'")
                return joblib.load(path), fallback

    for path in sorted(models_dir.rglob("*_model.pkl")):
        name = path.stem.replace("_model", "")
        print(f"  Falling back to '{name}' from {path}")
        return joblib.load(path), name

    raise FileNotFoundError(f"No loadable model found in {models_dir}")


def validate(data_dir: str, models_dir: str, output_path: str):
    data = Path(data_dir)
    models = Path(models_dir)
    out = Path(output_path)

    X_test = np.load(data / "X_test.npy", mmap_mode="r")
    y_test = np.load(data / "y_test.npy")

    if len(X_test) == 0:
        print("WARNING: Empty test set — writing placeholder report")
        out.write_text(json.dumps({"status": "no_test_data", "metrics": {}}, indent=2))
        return

    model, model_name = _load_best_model(models)
    print(f"Loaded model: {model_name} | Test samples: {len(X_test)}")

    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(X_test)[:, 1]
    else:
        y_prob = model.predict(X_test).astype(float)

    y_pred = (y_prob >= 0.5).astype(int)

    # Classification metrics
    tp = int(((y_pred == 1) & (y_test == 1)).sum())
    tn = int(((y_pred == 0) & (y_test == 0)).sum())
    fp = int(((y_pred == 1) & (y_test == 0)).sum())
    fn = int(((y_pred == 0) & (y_test == 1)).sum())
    accuracy = (tp + tn) / max(len(y_test), 1)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    # AUC-ROC
    try:
        from sklearn.metrics import roc_auc_score
        auc_roc = float(roc_auc_score(y_test, y_prob))
    except Exception:
        auc_roc = 0.0

    # Trading simulation on test set
    meta_path = data / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    n_train = int(meta.get("n_train", 0))
    n_val = int(meta.get("n_val", 0))

    enriched_path = None
    for candidate in [data / "enriched.parquet", data.parent / "enriched.parquet"]:
        if candidate.exists():
            enriched_path = candidate
            break

    trade_samples = []
    total_return_pct = 0.0
    trades_taken = 0
    wins = 0

    if enriched_path:
        df = pd.read_parquet(enriched_path)
        test_start = n_train + n_val
        test_end = test_start + len(y_test)
        df_test = df.iloc[test_start:test_end].reset_index(drop=True)

        threshold = 0.55
        take_mask = y_prob >= threshold
        trades_taken = int(take_mask.sum())

        if trades_taken > 0 and "pnl_pct" in df_test.columns:
            pnl_vals = df_test["pnl_pct"].fillna(0).values
            trade_pnls = pnl_vals[take_mask]
            wins = int((trade_pnls > 0).sum())
            equity = (1.0 + trade_pnls).cumprod()
            total_return_pct = round(float(equity[-1] - 1.0) * 100, 4)

        # Sample 10 trades for human-readable report
        sample_indices = list(range(min(10, len(df_test))))
        for i in sample_indices:
            ticker = df_test.iloc[i].get("ticker", "?") if "ticker" in df_test.columns else "?"
            actual = "WIN" if y_test[i] == 1 else "LOSS"
            predicted = "TRADE" if y_prob[i] >= 0.5 else "SKIP"
            conf = round(float(y_prob[i]), 3)
            pnl = round(float(df_test.iloc[i].get("pnl_pct", 0) * 100), 2) if "pnl_pct" in df_test.columns else "?"
            trade_samples.append({
                "trade_num": i + 1,
                "ticker": str(ticker),
                "prediction": predicted,
                "confidence": conf,
                "actual": actual,
                "pnl_pct": pnl,
                "summary": f"Trade #{i+1}: {ticker} -> Model says {predicted} (conf {conf:.2f}) -> Actual: {actual} (PnL: {pnl}%)",
            })

    metrics = {
        "model_name": model_name,
        "test_samples": len(y_test),
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "auc_roc": round(auc_roc, 4),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "trading_simulation": {
            "threshold": 0.55,
            "trades_taken": trades_taken,
            "wins": wins,
            "win_rate": round(wins / max(trades_taken, 1), 4),
            "total_return_pct": total_return_pct,
        },
    }

    # Pass/fail verdict
    verdict = "PASS" if (accuracy >= 0.52 and auc_roc >= 0.50) else "FAIL"

    report = {
        "status": verdict,
        "model_name": model_name,
        "metrics": metrics,
        "sample_trades": trade_samples,
        "summary": (
            f"Model '{model_name}' tested on {len(y_test)} samples: "
            f"Accuracy={accuracy:.1%}, AUC-ROC={auc_roc:.3f}, F1={f1:.3f}. "
            f"Simulated {trades_taken} trades at 0.55 threshold → {total_return_pct:.1f}% return. "
            f"Verdict: {verdict}"
        ),
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nValidation Report: {verdict}")
    print(f"  Accuracy:  {accuracy:.1%}")
    print(f"  AUC-ROC:   {auc_roc:.3f}")
    print(f"  Precision: {precision:.1%}")
    print(f"  Recall:    {recall:.1%}")
    print(f"  F1:        {f1:.3f}")
    print(f"  Trades simulated: {trades_taken}, Return: {total_return_pct:.1f}%")
    print(f"\nSample trades:")
    for s in trade_samples:
        print(f"  {s['summary']}")

    try:
        from report_to_phoenix import report_progress
        report_progress("validate_model", f"Model validation: {verdict}", 88, {
            "validation_report": metrics,
            "validation_verdict": verdict,
            "validation_samples": trade_samples,
        })
    except Exception:
        pass

    return report


def main():
    parser = argparse.ArgumentParser(description="Validate best model on held-out test set")
    parser.add_argument("--data", required=True, help="Preprocessing output directory")
    parser.add_argument("--models", required=True, help="Models directory")
    parser.add_argument("--output", required=True, help="Output validation_report.json path")
    args = parser.parse_args()
    validate(args.data, args.models, args.output)


if __name__ == "__main__":
    main()
