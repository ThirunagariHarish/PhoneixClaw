"""Preprocessing pipeline: 4-modality output for the 8-model training pipeline.

Reads enriched.parquet + candle_windows.npy + text_embeddings.npy and produces
time-based train/val/test splits for all data modalities.

Usage:
    python tools/preprocess.py --input output/enriched.parquet --output output/preprocessed/
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, LabelEncoder
import joblib

EXCLUDE_COLS = [
    "trade_id", "is_profitable", "entry_message_raw", "exit_messages_raw",
    "analyst", "channel", "ticker", "side", "option_type",
    "day_of_week", "hour_bucket", "market_regime", "vix_regime", "signal_type",
]

CATEGORICAL_COLS = [
    "analyst", "ticker", "side", "option_type",
    "day_of_week", "hour_bucket", "signal_type",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(args.input)

    df = pd.read_parquet(input_path)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns")

    if "entry_time" not in df.columns:
        df["entry_time"] = pd.to_datetime(df.get("entry_time", pd.Timestamp.now()))
    df = df.sort_values("entry_time").reset_index(drop=True)

    y = df["is_profitable"].astype(int).values

    # --- Tabular features ---
    feature_cols = [
        c for c in df.columns
        if c not in EXCLUDE_COLS
        and df[c].dtype in [np.float64, np.int64, float, int, "float32", "int32"]
    ]
    X = df[feature_cols].copy()

    # --- Time-based split ---
    n = len(X)
    train_end = int(n * 0.7)
    val_end = int(n * 0.85)

    X_train, y_train = X.iloc[:train_end], y[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y[val_end:]

    # Impute and scale tabular
    imputer = SimpleImputer(strategy="median")
    X_train_imp = imputer.fit_transform(X_train)
    X_val_imp = imputer.transform(X_val)
    X_test_imp = imputer.transform(X_test)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_imp)
    X_val_scaled = scaler.transform(X_val_imp)
    X_test_scaled = scaler.transform(X_test_imp)

    joblib.dump(imputer, output_dir / "imputer.pkl")
    joblib.dump(scaler, output_dir / "scaler.pkl")

    np.save(output_dir / "X_train.npy", X_train_scaled.astype(np.float32))
    np.save(output_dir / "X_val.npy", X_val_scaled.astype(np.float32))
    np.save(output_dir / "X_test.npy", X_test_scaled.astype(np.float32))
    np.save(output_dir / "y_train.npy", y_train)
    np.save(output_dir / "y_val.npy", y_val)
    np.save(output_dir / "y_test.npy", y_test)

    with open(output_dir / "feature_names.json", "w") as f:
        json.dump(feature_cols, f)

    print(f"Tabular: train={X_train_scaled.shape}, val={X_val_scaled.shape}, test={X_test_scaled.shape}")

    # --- Candle windows ---
    candle_path = input_path.parent / "candle_windows.npy"
    if candle_path.exists():
        candles = np.load(candle_path)
        assert len(candles) == n, f"Candle rows {len(candles)} != data rows {n}"
        np.save(output_dir / "candle_train.npy", candles[:train_end].astype(np.float32))
        np.save(output_dir / "candle_val.npy", candles[train_end:val_end].astype(np.float32))
        np.save(output_dir / "candle_test.npy", candles[val_end:].astype(np.float32))
        print(f"Candle windows: shape={candles.shape}")
    else:
        print("No candle_windows.npy found, skipping candle modality")

    # --- Text embeddings ---
    text_path = input_path.parent / "text_embeddings.npy"
    if text_path.exists():
        text_emb = np.load(text_path)
        assert len(text_emb) == n, f"Text rows {len(text_emb)} != data rows {n}"
        np.save(output_dir / "text_train.npy", text_emb[:train_end].astype(np.float32))
        np.save(output_dir / "text_val.npy", text_emb[train_end:val_end].astype(np.float32))
        np.save(output_dir / "text_test.npy", text_emb[val_end:].astype(np.float32))
        print(f"Text embeddings: shape={text_emb.shape}")
    else:
        print("No text_embeddings.npy found, skipping text modality")

    # --- Categoricals ---
    available_cats = [c for c in CATEGORICAL_COLS if c in df.columns]
    if available_cats:
        encoders = {}
        cat_arrays = []
        for col in available_cats:
            le = LabelEncoder()
            encoded = le.fit_transform(df[col].fillna("unknown").astype(str))
            cat_arrays.append(encoded.reshape(-1, 1))
            encoders[col] = le
        cat_matrix = np.hstack(cat_arrays)
        np.save(output_dir / "categoricals_train.npy", cat_matrix[:train_end].astype(np.int32))
        np.save(output_dir / "categoricals_val.npy", cat_matrix[train_end:val_end].astype(np.int32))
        np.save(output_dir / "categoricals_test.npy", cat_matrix[val_end:].astype(np.int32))
        joblib.dump(encoders, output_dir / "label_encoders.pkl")
        with open(output_dir / "categorical_names.json", "w") as f:
            json.dump(available_cats, f)
        print(f"Categoricals: {len(available_cats)} features, shape={cat_matrix.shape}")
    else:
        print("No categorical columns found, skipping categorical modality")

    # --- Summary ---
    summary = {
        "total_rows": n,
        "train_rows": train_end,
        "val_rows": val_end - train_end,
        "test_rows": n - val_end,
        "tabular_features": len(feature_cols),
        "has_candles": candle_path.exists(),
        "has_text": text_path.exists(),
        "categorical_features": len(available_cats),
    }
    with open(output_dir / "preprocessing_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Preprocessing complete: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    main()
