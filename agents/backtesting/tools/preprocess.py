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
    "analyst", "channel", "ticker", "side", "option_type", "trade_type",
    "day_of_week", "hour_bucket", "market_regime", "vix_regime", "signal_type",
    # Outcome/leakage columns — these encode the result, not predictive features
    "entry_price", "weighted_exit_price", "pnl_pct", "hold_duration_hours",
    "exit_time_first", "exit_time_final",
    "exit_pct_25", "exit_pct_50", "exit_pct_75", "exit_pct_100",
    "target_price", "stop_loss",
    # T1: multi-head labels are targets, not features
    "y_win", "y_pnl_pct", "y_mfe_atr", "y_mae_atr", "y_hold_minutes",
    "y_exit_bucket", "y_entry_slip_bps", "y_fill_60s",
]

EXIT_BUCKET_LABELS = ["lt_5m", "5_30m", "30m_2h", "2h_eod", "next_day"]

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

    # Guard: empty dataset — write placeholder outputs and exit
    if len(df) == 0:
        print("WARNING: No rows to preprocess — writing placeholder outputs and exiting.")
        placeholder = np.empty((0,), dtype=np.float64)
        np.save(output_dir / "X_train.npy", placeholder.reshape(0, 1))
        np.save(output_dir / "X_val.npy", placeholder.reshape(0, 1))
        np.save(output_dir / "X_test.npy", placeholder.reshape(0, 1))
        np.save(output_dir / "y_train.npy", placeholder)
        np.save(output_dir / "y_val.npy", placeholder)
        np.save(output_dir / "y_test.npy", placeholder)
        meta = {"feature_columns": [], "n_features": 0, "n_train": 0, "n_val": 0, "n_test": 0,
                "has_candles": False, "has_text": False, "categorical_columns": []}
        import json as _json
        (output_dir / "meta.json").write_text(_json.dumps(meta, indent=2))
        (output_dir / "preprocessed_meta.json").write_text(_json.dumps(meta, indent=2))
        print(f"Placeholder outputs written to {output_dir}")
        return

    if "entry_time" not in df.columns:
        df["entry_time"] = pd.to_datetime(df.get("entry_time", pd.Timestamp.now()))
    df = df.sort_values("entry_time").reset_index(drop=True)

    # NaN-safe: trades with no exit signal have is_profitable=NaN — treat as False
    y = df["is_profitable"].fillna(False).astype(int).values

    # --- Tabular features ---
    # Convert bool columns to int so they survive the numeric filter
    for c in df.columns:
        if pd.api.types.is_bool_dtype(df[c]):
            df[c] = df[c].astype(int)

    # Coerce object columns that are actually numeric (e.g. mixed float+None)
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    feature_cols = [
        c for c in df.columns
        if c not in EXCLUDE_COLS
        and pd.api.types.is_numeric_dtype(df[c])
    ]
    X = df[feature_cols].copy()

    # --- Time-based split ---
    n = len(X)
    if n < 5:
        train_end = max(1, n - 1)
        val_end = train_end
    else:
        train_end = int(n * 0.7)
        val_end = int(n * 0.85)

    train_end = max(1, train_end)
    val_end = max(train_end, val_end)

    X_train, y_train = X.iloc[:train_end], y[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y[val_end:]

    # Impute and scale tabular
    imputer = SimpleImputer(strategy="median")
    X_train_imp = imputer.fit_transform(X_train)
    n_features = X_train_imp.shape[1]

    if len(X_val) > 0:
        X_val_imp = imputer.transform(X_val)
    else:
        X_val_imp = np.empty((0, n_features), dtype=np.float64)

    if len(X_test) > 0:
        X_test_imp = imputer.transform(X_test)
    else:
        X_test_imp = np.empty((0, n_features), dtype=np.float64)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_imp)

    if len(X_val_imp) > 0:
        X_val_scaled = scaler.transform(X_val_imp)
    else:
        X_val_scaled = np.empty((0, n_features), dtype=np.float64)

    if len(X_test_imp) > 0:
        X_test_scaled = scaler.transform(X_test_imp)
    else:
        X_test_scaled = np.empty((0, n_features), dtype=np.float64)

    joblib.dump(imputer, output_dir / "imputer.pkl")
    joblib.dump(scaler, output_dir / "scaler.pkl")

    np.save(output_dir / "X_train.npy", X_train_scaled.astype(np.float32))
    np.save(output_dir / "X_val.npy", X_val_scaled.astype(np.float32))
    np.save(output_dir / "X_test.npy", X_test_scaled.astype(np.float32))
    np.save(output_dir / "y_train.npy", y_train)
    np.save(output_dir / "y_val.npy", y_val)
    np.save(output_dir / "y_test.npy", y_test)

    # --- T1: Multi-head label panel (regression + exit bucket) ------------------
    def _save_regression_label(col: str, stem: str) -> None:
        if col not in df.columns:
            return
        vals = pd.to_numeric(df[col], errors="coerce").astype(np.float32).values
        np.save(output_dir / f"{stem}_train.npy", vals[:train_end])
        np.save(output_dir / f"{stem}_val.npy", vals[train_end:val_end])
        np.save(output_dir / f"{stem}_test.npy", vals[val_end:])

    _save_regression_label("y_pnl_pct", "y_pnl")
    _save_regression_label("y_mfe_atr", "y_mfe_atr")
    _save_regression_label("y_mae_atr", "y_mae_atr")
    _save_regression_label("y_hold_minutes", "y_hold")
    _save_regression_label("y_entry_slip_bps", "y_slip")

    if "y_fill_60s" in df.columns:
        fill = pd.to_numeric(df["y_fill_60s"], errors="coerce").astype(np.float32).values
        np.save(output_dir / "y_fill_train.npy", fill[:train_end])
        np.save(output_dir / "y_fill_val.npy", fill[train_end:val_end])
        np.save(output_dir / "y_fill_test.npy", fill[val_end:])

    if "y_exit_bucket" in df.columns:
        bucket_to_idx = {b: i for i, b in enumerate(EXIT_BUCKET_LABELS)}
        bucket_int = df["y_exit_bucket"].fillna("5_30m").map(
            lambda b: bucket_to_idx.get(b, 1)
        ).astype(np.int32).values
        np.save(output_dir / "y_exit_bucket_train.npy", bucket_int[:train_end])
        np.save(output_dir / "y_exit_bucket_val.npy", bucket_int[train_end:val_end])
        np.save(output_dir / "y_exit_bucket_test.npy", bucket_int[val_end:])
        with open(output_dir / "exit_bucket_labels.json", "w") as f:
            json.dump(EXIT_BUCKET_LABELS, f)

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
        "label_heads": {
            head: bool(head in df.columns and df[head].notna().any())
            for head in [
                "y_win", "y_pnl_pct", "y_mfe_atr", "y_mae_atr",
                "y_hold_minutes", "y_exit_bucket", "y_entry_slip_bps", "y_fill_60s",
            ]
        },
    }
    with open(output_dir / "preprocessing_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    meta = {
        "feature_columns": feature_cols,
        "n_features": len(feature_cols),
        "n_train": train_end,
        "n_val": val_end - train_end,
        "n_test": n - val_end,
        "has_candles": candle_path.exists(),
        "has_text": text_path.exists(),
        "categorical_columns": available_cats,
    }
    with open(output_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Preprocessing complete: {json.dumps(summary, indent=2)}")
    try:
        from report_to_phoenix import report_progress
        report_progress("preprocess", "Preprocessing complete", 35, {
            "preprocessing_summary": summary,
            "feature_names": feature_cols,
            "feature_count": len(feature_cols),
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
