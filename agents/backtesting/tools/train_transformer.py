"""Train a small Transformer classifier for trade prediction (candle windows + tabular features).

Memory-optimised: uses small model dimensions, aggressive garbage collection,
and memory-mapped numpy loading to fit within 512 MB containers.
"""

import argparse
import gc
import json
import warnings
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
        print("PyTorch not available, skipping Transformer training")
        _write_fallback(output_dir, "pytorch not installed")
        return

    X_train = np.load(data_dir / "X_train.npy", mmap_mode="r").astype(np.float32)
    X_val = np.load(data_dir / "X_val.npy", mmap_mode="r").astype(np.float32)
    X_test = np.load(data_dir / "X_test.npy", mmap_mode="r").astype(np.float32)
    y_train = np.load(data_dir / "y_train.npy").astype(np.float32)
    y_val = np.load(data_dir / "y_val.npy").astype(np.float32)
    y_test = np.load(data_dir / "y_test.npy").astype(np.float32)

    candle_train_path = data_dir / "candle_train.npy"
    use_candles = candle_train_path.is_file()

    device = torch.device("cpu")

    if use_candles:
        candle_train = np.load(candle_train_path, mmap_mode="r").astype(np.float32)
        seq_len, candle_features = candle_train.shape[1], candle_train.shape[2]
        tabular_dim = X_train.shape[1]

        def _load_candle_split(name: str, n_rows: int) -> np.ndarray:
            p = data_dir / name
            if p.is_file():
                return np.load(p, mmap_mode="r").astype(np.float32)
            return np.zeros((n_rows, seq_len, candle_features), dtype=np.float32)

        candle_val = _load_candle_split("candle_val.npy", X_val.shape[0])
        candle_test = _load_candle_split("candle_test.npy", X_test.shape[0])

        D_MODEL = 48
        NHEAD = 4
        N_LAYERS = 2
        FF_DIM = 96

        class CandleTransformer(nn.Module):
            def __init__(self):
                super().__init__()
                self.max_seq_len = seq_len
                self.candle_proj = nn.Linear(candle_features, D_MODEL)
                self.pos_enc = nn.Parameter(torch.randn(1, seq_len, D_MODEL) * 0.02)
                encoder_layer = nn.TransformerEncoderLayer(
                    D_MODEL, NHEAD, dim_feedforward=FF_DIM, dropout=0.3, batch_first=True
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, N_LAYERS)
                self.tabular_proj = nn.Linear(tabular_dim, 32)
                self.classifier = nn.Sequential(
                    nn.Linear(D_MODEL + 32, 32),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(32, 1),
                    nn.Sigmoid(),
                )

            def forward(self, candle_seq, tabular):
                t = candle_seq.size(1)
                x = self.candle_proj(candle_seq) + self.pos_enc[:, :t]
                x = self.transformer(x)
                h_tab = self.tabular_proj(tabular)
                return self.classifier(torch.cat([x.mean(dim=1), h_tab], dim=1)).squeeze(-1)

        model = CandleTransformer().to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        BATCH = max(1, min(32, len(X_train)))

        train_ds = TensorDataset(
            torch.from_numpy(candle_train.copy()),
            torch.from_numpy(X_train.copy()),
            torch.FloatTensor(y_train),
        )
        train_dl = DataLoader(train_ds, batch_size=BATCH, shuffle=True)

        if len(X_val) > 0:
            val_ds = TensorDataset(
                torch.from_numpy(candle_val.copy()),
                torch.from_numpy(X_val.copy()),
                torch.FloatTensor(y_val),
            )
        else:
            val_ds = train_ds
        val_dl = DataLoader(val_ds, batch_size=BATCH)

        del candle_train, candle_val
        _cleanup()

        best_val_loss = float("inf")
        patience_counter = 0

        for epoch in range(60):
            model.train()
            for cb, xb, yb in train_dl:
                loss = criterion(model(cb, xb), yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for cb, xb, yb in val_dl:
                    val_loss += criterion(model(cb, xb), yb).item()

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                torch.save(model.state_dict(), output_dir / "transformer_model.pt")
            else:
                patience_counter += 1
                if patience_counter >= 10:
                    break

        model.load_state_dict(torch.load(output_dir / "transformer_model.pt", weights_only=True))
        model.eval()
        y_te = y_test
        with torch.no_grad():
            te_ds = TensorDataset(
                torch.from_numpy(candle_test.copy()),
                torch.from_numpy(X_test.copy()),
            )
            te_dl = DataLoader(te_ds, batch_size=BATCH)
            probs = []
            for cb, xb in te_dl:
                probs.append(model(cb, xb).numpy())
            y_prob = np.concatenate(probs, axis=0)
        y_pred = (y_prob > 0.5).astype(int)

        del candle_test
        _cleanup()

    else:
        SEQ_LEN = 10
        input_size = X_train.shape[1]

        def make_sequences(X, y, seq_len):
            if len(X) <= seq_len:
                x_f = X.astype(np.float32)
                pad = np.tile(x_f[0:1], (max(0, seq_len - len(X)), 1))
                xseq = np.vstack([pad, x_f])[-seq_len:] if len(pad) > 0 else x_f[-seq_len:]
                return np.expand_dims(xseq, 0), np.array([float(y[-1])], dtype=np.float32)
            xs, ys = [], []
            for i in range(seq_len, len(X)):
                xs.append(X[i - seq_len:i].astype(np.float32))
                ys.append(float(y[i]))
            return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)

        X_tr_seq, y_tr_seq = make_sequences(X_train, y_train, SEQ_LEN)
        X_val_seq, y_val_seq = make_sequences(X_val, y_val, SEQ_LEN)
        X_te_seq, y_te_seq = make_sequences(X_test, y_test, SEQ_LEN)

        D_MODEL = 48

        class TradeTransformer(nn.Module):
            def __init__(self, d_input):
                super().__init__()
                self.proj = nn.Linear(d_input, D_MODEL)
                layer = nn.TransformerEncoderLayer(
                    D_MODEL, 4, dim_feedforward=96, dropout=0.3, batch_first=True
                )
                self.encoder = nn.TransformerEncoder(layer, 2)
                self.head = nn.Sequential(
                    nn.Linear(D_MODEL, 32), nn.ReLU(), nn.Dropout(0.3),
                    nn.Linear(32, 1), nn.Sigmoid(),
                )

            def forward(self, x):
                x = self.proj(x)
                x = self.encoder(x)
                return self.head(x.mean(dim=1)).squeeze(-1)

        model = TradeTransformer(input_size).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        BATCH = max(1, min(32, len(X_tr_seq)))
        train_ds = TensorDataset(torch.FloatTensor(X_tr_seq), torch.FloatTensor(y_tr_seq))
        train_dl = DataLoader(train_ds, batch_size=BATCH, shuffle=True)
        if len(X_val_seq) > 0:
            val_ds = TensorDataset(torch.FloatTensor(X_val_seq), torch.FloatTensor(y_val_seq))
        else:
            val_ds = train_ds
        val_dl = DataLoader(val_ds, batch_size=BATCH)

        del X_tr_seq, X_val_seq
        _cleanup()

        best_val_loss = float("inf")
        patience_counter = 0

        for epoch in range(60):
            model.train()
            for xb, yb in train_dl:
                loss = criterion(model(xb), yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for xb, yb in val_dl:
                    val_loss += criterion(model(xb), yb).item()

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                torch.save(model.state_dict(), output_dir / "transformer_model.pt")
            else:
                patience_counter += 1
                if patience_counter >= 10:
                    break

        model.load_state_dict(torch.load(output_dir / "transformer_model.pt", weights_only=True))
        model.eval()
        y_te = y_te_seq
        with torch.no_grad():
            te_ds = TensorDataset(torch.FloatTensor(X_te_seq))
            te_dl = DataLoader(te_ds, batch_size=BATCH)
            probs = []
            for (xb,) in te_dl:
                probs.append(model(xb).numpy())
            y_prob = np.concatenate(probs, axis=0)
        y_pred = (y_prob > 0.5).astype(int)

        del X_te_seq
        _cleanup()

    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    results = {
        "model_name": "transformer",
        "accuracy": round(float(accuracy_score(y_te, y_pred)), 4),
        "precision": round(float(precision_score(y_te, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_te, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_te, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_te, y_prob)), 4) if len(set(y_te)) > 1 else 0.5,
        "profit_factor": 1.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "artifact_path": str(output_dir / "transformer_model.pt"),
    }
    with open(output_dir / "transformer_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"Transformer: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}")
    try:
        from report_to_phoenix import report_progress
        report_progress("train_transformer", f"Transformer trained: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}", 54)
    except Exception:
        pass


def _write_fallback(output_dir, error):
    results = {
        "model_name": "transformer", "accuracy": 0, "precision": 0, "recall": 0,
        "f1_score": 0, "auc_roc": 0.5, "profit_factor": 1.0,
        "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0, "error": error,
    }
    with open(output_dir / "transformer_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
