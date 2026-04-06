"""Intelligent model selector — picks optimal models based on dataset size and features.

Avoids wasting time training deep learning models on tiny datasets where tree models
converge just as well, while still leveraging neural nets when data is sufficient.

Usage:
    python tools/model_selector.py --data output/ --output output/model_selection.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# Available base models and their characteristics
MODEL_CATALOG = {
    "lightgbm":     {"type": "tree",  "min_rows": 30,   "speed": "fast",   "script": "train_lightgbm.py"},
    "catboost":     {"type": "tree",  "min_rows": 30,   "speed": "fast",   "script": "train_catboost.py"},
    "xgboost":      {"type": "tree",  "min_rows": 100,  "speed": "fast",   "script": "train_xgboost.py"},
    "rf":           {"type": "tree",  "min_rows": 100,  "speed": "fast",   "script": "train_rf.py"},
    "lstm":         {"type": "deep",  "min_rows": 500,  "speed": "medium", "script": "train_lstm.py"},
    "transformer":  {"type": "deep",  "min_rows": 1000, "speed": "slow",   "script": "train_transformer.py"},
    "tft":          {"type": "deep",  "min_rows": 1000, "speed": "slow",   "script": "train_tft.py"},
    "tcn":          {"type": "deep",  "min_rows": 800,  "speed": "medium", "script": "train_tcn.py"},
}

ENSEMBLE_MODELS = {
    "hybrid":       {"min_base_models": 2, "script": "train_hybrid.py"},
    "meta_learner": {"min_base_models": 2, "script": "train_meta_learner.py"},
}

# Rough time estimates in minutes per model (on single CPU/GPU, ~1000 rows)
TIME_ESTIMATES = {
    "lightgbm": 0.5, "catboost": 1.0, "xgboost": 0.5, "rf": 0.3,
    "lstm": 3.0, "transformer": 5.0, "tft": 5.0, "tcn": 4.0,
    "hybrid": 1.0, "meta_learner": 0.5,
}


def select_models(data_dir: str, strategy: str = "auto") -> dict:
    """Analyze dataset and select which models to train.

    Args:
        data_dir: Path to output/ directory containing enriched.parquet and preprocessed data
        strategy: Selection strategy — "auto" | "fast" | "full" | "tree-only"

    Returns:
        {
            "models": ["lightgbm", "catboost", ...],
            "ensemble": ["hybrid", "meta_learner"],
            "reason": "...",
            "dataset_stats": {"rows": N, "features": M, "has_candles": bool, "has_text": bool},
            "estimated_time_min": N
        }
    """
    data_path = Path(data_dir)

    # Gather dataset statistics
    stats = _analyze_dataset(data_path)
    n_rows = stats["rows"]
    has_candles = stats["has_candles"]
    has_text = stats["has_text"]
    n_features = stats["features"]

    # Strategy overrides
    if strategy == "full":
        selected = list(MODEL_CATALOG.keys())
        reason = "Full training: all models selected (strategy=full)"
    elif strategy == "tree-only":
        selected = [m for m, info in MODEL_CATALOG.items() if info["type"] == "tree"]
        reason = "Tree-only: skipping deep learning models (strategy=tree-only)"
    elif strategy == "fast":
        selected = ["lightgbm", "catboost"]
        reason = "Fast mode: only fastest tree models (strategy=fast)"
    else:
        # Auto selection based on data characteristics
        selected, reason = _auto_select(n_rows, n_features, has_candles, has_text)

    # Always add ensemble if we have >= 2 base models
    ensemble = []
    if len(selected) >= 2:
        ensemble = ["hybrid", "meta_learner"]

    # Estimate total time
    est_time = sum(TIME_ESTIMATES.get(m, 2.0) for m in selected + ensemble)
    # Scale by dataset size (linear approximation)
    scale_factor = max(0.5, min(3.0, n_rows / 1000.0))
    est_time *= scale_factor

    return {
        "models": selected,
        "ensemble": ensemble,
        "reason": reason,
        "dataset_stats": stats,
        "estimated_time_min": round(est_time, 1),
    }


def _analyze_dataset(data_path: Path) -> dict:
    """Gather statistics about the preprocessed dataset."""
    stats = {"rows": 0, "features": 0, "has_candles": False, "has_text": False}

    # Check enriched parquet for row count
    enriched = data_path / "enriched.parquet"
    if enriched.exists():
        try:
            df = pd.read_parquet(enriched)
            stats["rows"] = len(df)
            stats["features"] = len([c for c in df.columns if c not in (
                "is_profitable", "label", "ticker", "entry_time", "exit_time",
                "analyst", "message", "signal_raw",
            )])
        except Exception as e:
            print(f"  [model_selector] Could not read enriched.parquet: {e}")

    # Check for preprocessed numpy arrays as fallback
    if stats["rows"] == 0:
        x_train = data_path / "X_train.npy"
        if x_train.exists():
            try:
                arr = np.load(str(x_train), mmap_mode="r")
                stats["rows"] = arr.shape[0]
                stats["features"] = arr.shape[1] if arr.ndim > 1 else 0
            except Exception:
                pass

    # Check for candle windows
    candle_train = data_path / "candle_train.npy"
    stats["has_candles"] = candle_train.exists() and candle_train.stat().st_size > 100

    # Check for text embeddings
    text_train = data_path / "text_train.npy"
    stats["has_text"] = text_train.exists() and text_train.stat().st_size > 100

    return stats


def _auto_select(n_rows: int, n_features: int, has_candles: bool, has_text: bool) -> tuple[list[str], str]:
    """Auto-select models based on dataset characteristics."""
    selected = []
    reasons = []

    if n_rows < 50:
        # Very small dataset — only fastest tree models
        selected = ["lightgbm", "catboost"]
        reasons.append(f"Very small dataset ({n_rows} rows) — tree models only")
        return selected, "; ".join(reasons)

    # Always include tree models — they're fast and reliable
    if n_rows >= 30:
        selected.extend(["lightgbm", "catboost"])
        reasons.append("LightGBM + CatBoost: fast, strong baseline")

    if n_rows >= 200:
        selected.extend(["xgboost", "rf"])
        reasons.append(f"XGBoost + RF: {n_rows} rows sufficient for full tree ensemble")

    # Deep learning models — only when data justifies the cost
    if n_rows >= 500:
        selected.append("lstm")
        reasons.append(f"LSTM: {n_rows} rows meets threshold for sequence modeling")

    if n_rows >= 1000:
        # Pick ONE of transformer/tft/tcn based on data characteristics
        if has_candles:
            # TCN is best for fixed-length candle window sequences
            selected.append("tcn")
            reasons.append("TCN: candle window data available, good for fixed sequences")
        elif n_features > 100:
            # TFT handles high-dimensional features well
            selected.append("tft")
            reasons.append(f"TFT: high feature count ({n_features}), good for attention over features")
        else:
            selected.append("transformer")
            reasons.append("Transformer: general-purpose deep model for tabular sequences")

    return selected, "; ".join(reasons)


def main():
    parser = argparse.ArgumentParser(description="Select optimal models for backtesting")
    parser.add_argument("--data", required=True, help="Path to output/ directory")
    parser.add_argument("--output", required=True, help="Path to write model_selection.json")
    parser.add_argument("--strategy", default="auto", choices=["auto", "fast", "full", "tree-only"],
                        help="Model selection strategy")
    args = parser.parse_args()

    result = select_models(args.data, args.strategy)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))

    print(f"\n  Model Selection Complete")
    print(f"  Dataset: {result['dataset_stats']['rows']} rows, {result['dataset_stats']['features']} features")
    print(f"  Selected: {', '.join(result['models'])}")
    if result['ensemble']:
        print(f"  Ensemble: {', '.join(result['ensemble'])}")
    print(f"  Reason: {result['reason']}")
    print(f"  Estimated time: {result['estimated_time_min']} min")
    print(f"  Written to: {args.output}\n")


if __name__ == "__main__":
    main()
