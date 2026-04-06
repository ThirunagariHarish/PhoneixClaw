"""Train Temporal Fusion Transformer for trade prediction.

Memory-optimised: uses small model dimensions, aggressive garbage collection,
and skips the heavy pytorch-forecasting path to fit within 512 MB containers.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import numpy as np


def _cleanup():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _torch_load_state(path: Path, map_location=None):
    import torch
    try:
        return torch.load(path, weights_only=True, map_location=map_location)
    except TypeError:
        return torch.load(path, map_location=map_location)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        print("PyTorch not available, skipping TFT training")
        _write_fallback(output_dir, "pytorch not installed")
        return

    X_train = np.load(data_dir / "X_train.npy", mmap_mode="r").astype(np.float32)
    X_test = np.load(data_dir / "X_test.npy", mmap_mode="r").astype(np.float32)
    y_train = np.load(data_dir / "y_train.npy").astype(np.float32)
    y_test = np.load(data_dir / "y_test.npy").astype(np.float32)

    candle_train = np.load(data_dir / "candle_train.npy", mmap_mode="r").astype(np.float32) \
        if (data_dir / "candle_train.npy").exists() else None
    candle_test = np.load(data_dir / "candle_test.npy", mmap_mode="r").astype(np.float32) \
        if (data_dir / "candle_test.npy").exists() else None

    if candle_train is None or candle_test is None:
        print("No candle windows found, skipping TFT")
        _write_fallback(output_dir, "candle data missing")
        return

    candle_features = candle_train.shape[2]
    tabular_dim = X_train.shape[1]

    D_MODEL = 48
    NHEAD = 4
    N_LAYERS = 2
    FF_DIM = 96

    class SimplifiedTFT(nn.Module):
        def __init__(self):
            super().__init__()
            self.candle_proj = nn.Linear(candle_features, D_MODEL)
            self.pos_enc = nn.Parameter(torch.randn(1, 30, D_MODEL) * 0.02)
            encoder_layer = nn.TransformerEncoderLayer(
                D_MODEL, NHEAD, dim_feedforward=FF_DIM, dropout=0.2, batch_first=True
            )
            self.temporal_encoder = nn.TransformerEncoder(encoder_layer, N_LAYERS)
            self.static_proj = nn.Linear(tabular_dim, D_MODEL)
            self.gate = nn.Sequential(nn.Linear(D_MODEL * 2, D_MODEL), nn.Sigmoid())
            self.classifier = nn.Sequential(
                nn.Linear(D_MODEL, 24), nn.ReLU(), nn.Dropout(0.2),
                nn.Linear(24, 1), nn.Sigmoid()
            )

        def forward(self, candle_seq, tabular):
            temporal = self.candle_proj(candle_seq) + self.pos_enc[:, :candle_seq.size(1)]
            temporal = self.temporal_encoder(temporal).mean(dim=1)
            static = self.static_proj(tabular)
            gate_input = torch.cat([temporal, static], dim=1)
            g = self.gate(gate_input)
            gated = g * temporal + (1 - g) * static
            return self.classifier(gated).squeeze(-1)

    device = torch.device("cpu")
    model = SimplifiedTFT().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=5e-4, weight_decay=1e-5)
    criterion = nn.BCELoss()

    n = len(X_train)
    val_split = int(n * 0.85)
    val_split = max(1, min(val_split, n - 1))

    c_tr = candle_train[:val_split].copy()
    c_vl = candle_train[val_split:].copy()
    X_tr = X_train[:val_split].copy()
    X_vl = X_train[val_split:].copy()
    y_tr = y_train[:val_split]
    y_vl = y_train[val_split:]

    del candle_train
    _cleanup()

    if len(X_vl) == 0:
        c_vl, X_vl, y_vl = c_tr, X_tr, y_tr

    BATCH = max(1, min(32, len(X_tr)))
    train_ds = TensorDataset(
        torch.from_numpy(c_tr), torch.from_numpy(X_tr), torch.FloatTensor(y_tr)
    )
    train_dl = DataLoader(train_ds, batch_size=BATCH, shuffle=True)

    cv_t = torch.from_numpy(c_vl)
    xv_t = torch.from_numpy(X_vl)
    yv_t = torch.FloatTensor(y_vl)

    del c_tr, c_vl, X_tr, X_vl
    _cleanup()

    best_val_loss = float("inf")
    patience_counter = 0

    for _epoch in range(80):
        model.train()
        for cb, tb, yb in train_dl:
            loss = criterion(model(cb, tb), yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_pred = model(cv_t, xv_t)
            val_loss = criterion(val_pred, yv_t).item()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), output_dir / "tft_model.pt")
        else:
            patience_counter += 1
            if patience_counter >= 12:
                break

    model.load_state_dict(_torch_load_state(output_dir / "tft_model.pt", map_location=device))
    model.eval()

    del cv_t, xv_t, yv_t, train_ds, train_dl
    _cleanup()

    ct_np = candle_test.copy()
    xt_np = X_test.copy()
    del candle_test
    _cleanup()

    with torch.no_grad():
        y_prob = model(
            torch.from_numpy(ct_np), torch.from_numpy(xt_np)
        ).numpy()
        y_pred = (y_prob > 0.5).astype(int)

    del ct_np, xt_np
    _cleanup()

    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    results = {
        "model_name": "tft",
        "backend": "simplified",
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 4) if len(set(y_test)) > 1 else 0.5,
        "profit_factor": 1.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "artifact_path": str(output_dir / "tft_model.pt"),
    }
    with open(output_dir / "tft_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"TFT: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}")
    try:
        from report_to_phoenix import report_progress
        report_progress("train_tft", f"TFT trained: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}", 56)
    except Exception:
        pass


def _write_fallback(output_dir, error):
    results = {
        "model_name": "tft", "accuracy": 0, "precision": 0, "recall": 0,
        "f1_score": 0, "auc_roc": 0.5, "profit_factor": 1.0,
        "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0, "error": error,
    }
    with open(output_dir / "tft_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
