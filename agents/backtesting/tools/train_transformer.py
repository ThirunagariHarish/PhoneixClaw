"""Train a small Transformer classifier for trade prediction (candle windows + tabular features)."""

import argparse
import json
import warnings
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    X_train = np.load(data_dir / "X_train.npy")
    X_val = np.load(data_dir / "X_val.npy")
    X_test = np.load(data_dir / "X_test.npy")
    y_train = np.load(data_dir / "y_train.npy")
    y_val = np.load(data_dir / "y_val.npy")
    y_test = np.load(data_dir / "y_test.npy")

    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        print("PyTorch not available, skipping Transformer training")
        results = {
            "model_name": "transformer",
            "accuracy": 0,
            "precision": 0,
            "recall": 0,
            "f1_score": 0,
            "auc_roc": 0.5,
            "profit_factor": 1.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "error": "pytorch not installed",
        }
        with open(output_dir / "transformer_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    candle_train_path = data_dir / "candle_train.npy"
    use_candles = candle_train_path.is_file()

    if use_candles:
        candle_train = np.load(candle_train_path).astype(np.float32)
        seq_len, candle_features = candle_train.shape[1], candle_train.shape[2]
        tabular_dim = X_train.shape[1]

        def _load_candle_split(name: str, n_rows: int) -> np.ndarray:
            p = data_dir / name
            if p.is_file():
                return np.load(p).astype(np.float32)
            warnings.warn(
                f"{name} not found; using zeros shaped ({n_rows}, {seq_len}, {candle_features}). "
                "Add split candle arrays for meaningful validation/test candle input.",
                UserWarning,
                stacklevel=2,
            )
            return np.zeros((n_rows, seq_len, candle_features), dtype=np.float32)

        candle_val = _load_candle_split("candle_val.npy", X_val.shape[0])
        candle_test = _load_candle_split("candle_test.npy", X_test.shape[0])

        for split, c_x, cy in (
            ("train", candle_train, X_train),
            ("val", candle_val, X_val),
            ("test", candle_test, X_test),
        ):
            if c_x.shape[0] != cy.shape[0]:
                raise ValueError(
                    f"candle_{split} length {c_x.shape[0]} does not match X_{split} length {cy.shape[0]}"
                )

        class CandleTransformer(nn.Module):
            def __init__(
                self,
                candle_features=15,
                tabular_dim=200,
                max_seq_len=30,
                d_model=128,
                nhead=4,
                n_layers=2,
            ):
                super().__init__()
                self.max_seq_len = max_seq_len
                self.candle_proj = nn.Linear(candle_features, d_model)
                self.pos_enc = nn.Parameter(torch.randn(1, max_seq_len, d_model) * 0.02)
                encoder_layer = nn.TransformerEncoderLayer(
                    d_model, nhead, dim_feedforward=256, dropout=0.3, batch_first=True
                )
                self.transformer = nn.TransformerEncoder(encoder_layer, n_layers)
                self.tabular_proj = nn.Linear(tabular_dim, 64)
                self.classifier = nn.Sequential(
                    nn.Linear(d_model + 64, 64),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(64, 1),
                    nn.Sigmoid(),
                )

            def forward(self, candle_seq, tabular):
                t = candle_seq.size(1)
                if t > self.max_seq_len:
                    raise ValueError(f"candle sequence length {t} exceeds pos_enc length {self.max_seq_len}")
                x = self.candle_proj(candle_seq) + self.pos_enc[:, :t]
                x = self.transformer(x)
                h_tab = self.tabular_proj(tabular)
                return self.classifier(torch.cat([x.mean(dim=1), h_tab], dim=1)).squeeze(-1)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = CandleTransformer(candle_features, tabular_dim, max_seq_len=seq_len).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        train_ds = TensorDataset(
            torch.FloatTensor(candle_train),
            torch.FloatTensor(X_train.astype(np.float32)),
            torch.FloatTensor(y_train.astype(np.float32)),
        )
        train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)
        val_ds = TensorDataset(
            torch.FloatTensor(candle_val),
            torch.FloatTensor(X_val.astype(np.float32)),
            torch.FloatTensor(y_val.astype(np.float32)),
        )
        val_dl = DataLoader(val_ds, batch_size=128)

        best_val_loss = float("inf")
        patience_counter = 0

        for epoch in range(80):
            model.train()
            for cb, xb, yb in train_dl:
                cb, xb, yb = cb.to(device), xb.to(device), yb.to(device)
                loss = criterion(model(cb, xb), yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for cb, xb, yb in val_dl:
                    cb, xb, yb = cb.to(device), xb.to(device), yb.to(device)
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
                torch.FloatTensor(candle_test),
                torch.FloatTensor(X_test.astype(np.float32)),
            )
            te_dl = DataLoader(te_ds, batch_size=128)
            probs = []
            for cb, xb in te_dl:
                cb, xb = cb.to(device), xb.to(device)
                probs.append(model(cb, xb).cpu().numpy())
            y_prob = np.concatenate(probs, axis=0)
        y_pred = (y_prob > 0.5).astype(int)

    else:
        warnings.warn(
            "candle_train.npy not found; falling back to sliding windows over tabular rows "
            "(consecutive trades, not true candle time series).",
            UserWarning,
            stacklevel=2,
        )

        SEQ_LEN = 10
        input_size = X_train.shape[1]

        def make_sequences(X, y, seq_len):
            xs, ys = [], []
            for i in range(seq_len, len(X)):
                xs.append(X[i - seq_len : i])
                ys.append(y[i])
            return np.array(xs), np.array(ys)

        X_tr_seq, y_tr_seq = make_sequences(X_train, y_train, SEQ_LEN)
        X_val_seq, y_val_seq = make_sequences(X_val, y_val, SEQ_LEN)
        X_te_seq, y_te_seq = make_sequences(X_test, y_test, SEQ_LEN)

        class TradeTransformer(nn.Module):
            def __init__(self, d_input, d_model=128, nhead=4, num_layers=2):
                super().__init__()
                self.proj = nn.Linear(d_input, d_model)
                layer = nn.TransformerEncoderLayer(
                    d_model, nhead, dim_feedforward=256, dropout=0.3, batch_first=True
                )
                self.encoder = nn.TransformerEncoder(layer, num_layers)
                self.head = nn.Sequential(
                    nn.Linear(d_model, 64),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(64, 1),
                    nn.Sigmoid(),
                )

            def forward(self, x):
                x = self.proj(x)
                x = self.encoder(x)
                return self.head(x.mean(dim=1)).squeeze(-1)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = TradeTransformer(input_size).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        train_ds = TensorDataset(torch.FloatTensor(X_tr_seq), torch.FloatTensor(y_tr_seq))
        train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)
        val_ds = TensorDataset(torch.FloatTensor(X_val_seq), torch.FloatTensor(y_val_seq))
        val_dl = DataLoader(val_ds, batch_size=128)

        best_val_loss = float("inf")
        patience_counter = 0

        for epoch in range(80):
            model.train()
            for xb, yb in train_dl:
                xb, yb = xb.to(device), yb.to(device)
                loss = criterion(model(xb), yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for xb, yb in val_dl:
                    xb, yb = xb.to(device), yb.to(device)
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
            te_dl = DataLoader(te_ds, batch_size=128)
            probs = []
            for (xb,) in te_dl:
                xb = xb.to(device)
                probs.append(model(xb).cpu().numpy())
            y_prob = np.concatenate(probs, axis=0)
        y_pred = (y_prob > 0.5).astype(int)

    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

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


if __name__ == "__main__":
    main()
