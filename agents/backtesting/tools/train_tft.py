"""Train Temporal Fusion Transformer for trade prediction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def _stack_tabular_categoricals(
    X_train: np.ndarray,
    X_test: np.ndarray,
    data_dir: Path,
) -> tuple[np.ndarray, np.ndarray]:
    cat_train = np.load(data_dir / "categoricals_train.npy") if (data_dir / "categoricals_train.npy").exists() else None
    cat_test = np.load(data_dir / "categoricals_test.npy") if (data_dir / "categoricals_test.npy").exists() else None
    if cat_train is not None and cat_test is not None:
        return np.hstack([X_train, cat_train.astype(np.float32)]), np.hstack([X_test, cat_test.astype(np.float32)])
    return X_train, X_test


def _torch_load_state(path: Path, map_location=None):
    import torch

    try:
        return torch.load(path, weights_only=True, map_location=map_location)
    except TypeError:
        return torch.load(path, map_location=map_location)


def _import_lightning():
    try:
        import lightning.pytorch as pl  # type: ignore

        return pl
    except ImportError:
        import pytorch_lightning as pl  # type: ignore

        return pl


def _try_pytorch_forecasting(
    candle_train: np.ndarray,
    candle_test: np.ndarray,
    X_train: np.ndarray,
    X_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    output_dir: Path,
) -> bool:
    try:
        import pandas as pd
        import torch
        from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
        from pytorch_forecasting.metrics import QuantileLoss
    except ImportError:
        return False

    pl = _import_lightning()

    N, T, Fdim = candle_train.shape
    S = X_train.shape[1]
    if T < 3:
        return False

    def to_long_df(candle: np.ndarray, X: np.ndarray, y: np.ndarray) -> "pd.DataFrame":
        rows = []
        for i in range(len(y)):
            for t in range(T):
                row = {
                    "series": i,
                    "time_idx": t,
                    "target": float(y[i]),
                }
                for j in range(Fdim):
                    row[f"cv_{j}"] = float(candle[i, t, j])
                for j in range(S):
                    row[f"st_{j}"] = float(X[i, j])
                rows.append(row)
        return pd.DataFrame(rows)

    n_train_series = int(N * 0.85)
    if n_train_series < 1 or n_train_series >= N:
        return False

    df_train = to_long_df(candle_train[:n_train_series], X_train[:n_train_series], y_train[:n_train_series])
    df_val = to_long_df(candle_train[n_train_series:], X_train[n_train_series:], y_train[n_train_series:])

    cv_cols = [f"cv_{j}" for j in range(Fdim)]
    st_cols = [f"st_{j}" for j in range(S)]
    max_encoder_length = max(1, T - 1)
    pred_len = 1

    trainer_kw = dict(accelerator="cpu", devices=1)

    try:
        training = TimeSeriesDataSet(
            df_train,
            time_idx="time_idx",
            target="target",
            group_ids=["series"],
            min_encoder_length=max_encoder_length // 2,
            max_encoder_length=max_encoder_length,
            min_prediction_length=pred_len,
            max_prediction_length=pred_len,
            time_varying_unknown_reals=cv_cols,
            static_reals=st_cols,
            add_relative_time_idx=True,
            add_target_scales=True,
            add_encoder_length=True,
            target_normalizer=None,
        )
        validation = TimeSeriesDataSet.from_dataset(training, df_val, predict=True, stop_randomization=True)
    except Exception:
        return False

    n_val_series = N - n_train_series
    train_bs = max(1, min(64, n_train_series))
    val_bs = max(1, min(128, max(n_val_series, 1)))
    train_loader = training.to_dataloader(train=True, batch_size=train_bs, num_workers=0)
    val_loader = validation.to_dataloader(train=False, batch_size=val_bs, num_workers=0)

    tft = TemporalFusionTransformer.from_dataset(
        training,
        learning_rate=0.03,
        hidden_size=32,
        attention_head_size=4,
        dropout=0.1,
        hidden_continuous_size=16,
        output_size=7,
        loss=QuantileLoss(),
    )

    early_stop = pl.callbacks.EarlyStopping(monitor="val_loss", patience=5, mode="min")
    trainer = pl.Trainer(
        max_epochs=30,
        enable_checkpointing=False,
        enable_model_summary=False,
        logger=False,
        callbacks=[early_stop],
        **trainer_kw,
    )
    try:
        trainer.fit(tft, train_dataloaders=train_loader, val_dataloaders=val_loader)
    except Exception:
        return False

    ckpt_path = output_dir / "tft_model.ckpt"
    trainer.save_checkpoint(ckpt_path)

    df_test = to_long_df(candle_test, X_test, y_test)
    try:
        test_ds = TimeSeriesDataSet.from_dataset(training, df_test, predict=True, stop_randomization=True)
        n_test_series = len(y_test)
        test_bs = max(1, min(128, n_test_series))
        test_loader = test_ds.to_dataloader(train=False, batch_size=test_bs, num_workers=0)
    except Exception:
        return False

    try:
        raw = tft.predict(
            test_loader,
            mode="prediction",
            return_x=False,
            trainer_kwargs=trainer_kw,
        )
    except Exception:
        return False

    if isinstance(raw, torch.Tensor):
        y_prob = raw.detach().cpu().numpy().reshape(-1)
    elif hasattr(raw, "output"):
        y_prob = raw.output.detach().cpu().numpy().reshape(-1)
    else:
        return False

    if len(y_prob) != len(y_test):
        return False

    y_pred = (y_prob > 0.5).astype(int)

    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    results = {
        "model_name": "tft",
        "backend": "pytorch_forecasting",
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 4) if len(set(y_test)) > 1 else 0.5,
        "profit_factor": 1.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "artifact_path": str(ckpt_path),
    }
    with open(output_dir / "tft_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"TFT (pytorch-forecasting): accuracy={results['accuracy']} auc={results['auc_roc']}")
    return True


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

    X_train, X_test = _stack_tabular_categoricals(X_train, X_test, data_dir)

    candle_train = np.load(data_dir / "candle_train.npy") if (data_dir / "candle_train.npy").exists() else None
    candle_test = np.load(data_dir / "candle_test.npy") if (data_dir / "candle_test.npy").exists() else None

    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        print("PyTorch not available, skipping TFT training")
        results = {"model_name": "tft", "accuracy": 0, "error": "pytorch not installed"}
        with open(output_dir / "tft_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    if candle_train is None:
        print("No candle windows found, skipping TFT")
        results = {"model_name": "tft", "accuracy": 0, "error": "candle_train.npy missing"}
        with open(output_dir / "tft_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    if _try_pytorch_forecasting(candle_train, candle_test, X_train, X_test, y_train, y_test, output_dir):
        return

    class SimplifiedTFT(nn.Module):
        def __init__(self, candle_features, tabular_dim, d_model=64, nhead=4, n_layers=2):
            super().__init__()
            self.candle_proj = nn.Linear(candle_features, d_model)
            self.pos_enc = nn.Parameter(torch.randn(1, 30, d_model) * 0.02)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model, nhead, dim_feedforward=128, dropout=0.2, batch_first=True
            )
            self.temporal_encoder = nn.TransformerEncoder(encoder_layer, n_layers)
            self.static_proj = nn.Linear(tabular_dim, d_model)
            self.gate = nn.Sequential(nn.Linear(d_model * 2, d_model), nn.Sigmoid())
            self.classifier = nn.Sequential(
                nn.Linear(d_model, 32), nn.ReLU(), nn.Dropout(0.2), nn.Linear(32, 1), nn.Sigmoid()
            )

        def forward(self, candle_seq, tabular):
            temporal = self.candle_proj(candle_seq) + self.pos_enc[:, : candle_seq.size(1)]
            temporal = self.temporal_encoder(temporal).mean(dim=1)
            static = self.static_proj(tabular)
            gate_input = torch.cat([temporal, static], dim=1)
            g = self.gate(gate_input)
            gated = g * temporal + (1 - g) * static
            return self.classifier(gated).squeeze(-1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if candle_test is None:
        print("candle_test.npy missing, skipping TFT")
        results = {"model_name": "tft", "accuracy": 0, "error": "candle_test.npy missing"}
        with open(output_dir / "tft_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    candle_features = candle_train.shape[2]
    tabular_dim = X_train.shape[1]

    model = SimplifiedTFT(candle_features, tabular_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=5e-4, weight_decay=1e-5)
    criterion = nn.BCELoss()

    n = len(X_train)
    val_split = int(n * 0.85)
    if val_split <= 0:
        val_split = n
    if val_split >= n and n > 1:
        val_split = n - 1
    X_tr, X_vl = X_train[:val_split], X_train[val_split:]
    c_tr, c_vl = candle_train[:val_split], candle_train[val_split:]
    y_tr, y_vl = y_train[:val_split], y_train[val_split:]
    if len(X_vl) == 0:
        c_vl, X_vl, y_vl = c_tr, X_tr, y_tr

    train_ds = TensorDataset(torch.FloatTensor(c_tr), torch.FloatTensor(X_tr), torch.FloatTensor(y_tr))
    train_bs = max(1, min(64, len(train_ds)))
    train_dl = DataLoader(train_ds, batch_size=train_bs, shuffle=True)

    best_val_loss = float("inf")
    patience_counter = 0

    for _epoch in range(100):
        model.train()
        for cb, tb, yb in train_dl:
            cb, tb, yb = cb.to(device), tb.to(device), yb.to(device)
            loss = criterion(model(cb, tb), yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_pred = model(torch.FloatTensor(c_vl).to(device), torch.FloatTensor(X_vl).to(device))
            val_loss = criterion(val_pred, torch.FloatTensor(y_vl).to(device)).item()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), output_dir / "tft_model.pt")
        else:
            patience_counter += 1
            if patience_counter >= 15:
                break

    model.load_state_dict(_torch_load_state(output_dir / "tft_model.pt", map_location=device))
    model.eval()
    with torch.no_grad():
        y_prob = model(
            torch.FloatTensor(candle_test).to(device), torch.FloatTensor(X_test).to(device)
        ).cpu().numpy()
        y_pred = (y_prob > 0.5).astype(int)

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
    print(f"TFT: accuracy={results['accuracy']} auc={results['auc_roc']}")


if __name__ == "__main__":
    main()
