"""Train LSTM neural network for trade prediction (candle windows + tabular features)."""

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
        print("PyTorch not available, skipping LSTM training")
        results = {
            "model_name": "lstm",
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
        with open(output_dir / "lstm_results.json", "w") as f:
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

        class CandleLSTM(nn.Module):
            def __init__(self, candle_features=15, tabular_dim=200, hidden=128, n_layers=2):
                super().__init__()
                self.lstm = nn.LSTM(
                    candle_features, hidden, n_layers, batch_first=True, dropout=0.3
                )
                self.tabular_proj = nn.Linear(tabular_dim, 64)
                self.classifier = nn.Sequential(
                    nn.Linear(hidden + 64, 64),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(64, 1),
                    nn.Sigmoid(),
                )

            def forward(self, candle_seq, tabular):
                _, (hn, _) = self.lstm(candle_seq)
                h_tab = self.tabular_proj(tabular)
                return self.classifier(torch.cat([hn[-1], h_tab], dim=1)).squeeze(-1)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = CandleLSTM(candle_features, tabular_dim).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        train_ds = TensorDataset(
            torch.FloatTensor(candle_train),
            torch.FloatTensor(X_train.astype(np.float32)),
            torch.FloatTensor(y_train.astype(np.float32)),
        )
        train_bs = max(1, min(64, len(train_ds)))
        train_dl = DataLoader(train_ds, batch_size=train_bs, shuffle=True)
        if len(X_val) > 0:
            val_ds = TensorDataset(
                torch.FloatTensor(candle_val),
                torch.FloatTensor(X_val.astype(np.float32)),
                torch.FloatTensor(y_val.astype(np.float32)),
            )
        else:
            val_ds = train_ds
        val_bs = max(1, min(128, len(val_ds)))
        val_dl = DataLoader(val_ds, batch_size=val_bs)

        best_val_loss = float("inf")
        patience = 10
        patience_counter = 0

        for epoch in range(100):
            model.train()
            for cb, xb, yb in train_dl:
                cb, xb, yb = cb.to(device), xb.to(device), yb.to(device)
                pred = model(cb, xb)
                loss = criterion(pred, yb)
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
                torch.save(model.state_dict(), output_dir / "lstm_model.pt")
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

        model.load_state_dict(torch.load(output_dir / "lstm_model.pt", weights_only=True))
        model.eval()
        y_te = y_test
        with torch.no_grad():
            te_ds = TensorDataset(
                torch.FloatTensor(candle_test),
                torch.FloatTensor(X_test.astype(np.float32)),
            )
            te_bs = max(1, min(128, len(te_ds)))
            te_dl = DataLoader(te_ds, batch_size=te_bs)
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
        n_tab_max = max(len(X_train), len(X_val), len(X_test))
        seq_len_eff = min(SEQ_LEN, max(1, n_tab_max - 1)) if n_tab_max > 0 else 1

        def make_sequences(X, y, seq_len):
            feat_dim = X.shape[1]
            xs, ys = [], []
            if len(X) == 0:
                return (
                    np.zeros((0, seq_len, feat_dim), dtype=np.float32),
                    np.zeros((0,), dtype=np.float32),
                )
            if len(X) <= seq_len:
                pad_rows = seq_len - len(X)
                x_f = X.astype(np.float32)
                if pad_rows > 0:
                    pad = np.tile(x_f[0:1], (pad_rows, 1))
                    xseq = np.vstack([pad, x_f])
                else:
                    xseq = x_f
                xs.append(xseq[-seq_len:])
                ys.append(float(y[-1]))
                return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)
            for i in range(seq_len, len(X)):
                xs.append(X[i - seq_len : i].astype(np.float32))
                ys.append(float(y[i]))
            return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)

        X_tr_seq, y_tr_seq = make_sequences(X_train, y_train, seq_len_eff)
        X_val_seq, y_val_seq = make_sequences(X_val, y_val, seq_len_eff)
        X_te_seq, y_te_seq = make_sequences(X_test, y_test, seq_len_eff)

        class TradeLSTM(nn.Module):
            def __init__(self, inp, hidden=128, layers=2):
                super().__init__()
                self.lstm = nn.LSTM(inp, hidden, layers, batch_first=True, dropout=0.3)
                self.fc = nn.Sequential(
                    nn.Linear(hidden, 64),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(64, 1),
                    nn.Sigmoid(),
                )

            def forward(self, x):
                _, (hn, _) = self.lstm(x)
                return self.fc(hn[-1]).squeeze(-1)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = TradeLSTM(input_size).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        criterion = nn.BCELoss()

        train_ds = TensorDataset(torch.FloatTensor(X_tr_seq), torch.FloatTensor(y_tr_seq))
        train_bs = max(1, min(64, len(train_ds)))
        train_dl = DataLoader(train_ds, batch_size=train_bs, shuffle=True)
        if len(X_val_seq) > 0:
            val_ds = TensorDataset(torch.FloatTensor(X_val_seq), torch.FloatTensor(y_val_seq))
        else:
            val_ds = train_ds
        val_bs = max(1, min(128, len(val_ds)))
        val_dl = DataLoader(val_ds, batch_size=val_bs)

        best_val_loss = float("inf")
        patience = 10
        patience_counter = 0

        for epoch in range(100):
            model.train()
            for xb, yb in train_dl:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                loss = criterion(pred, yb)
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
                torch.save(model.state_dict(), output_dir / "lstm_model.pt")
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

        model.load_state_dict(torch.load(output_dir / "lstm_model.pt", weights_only=True))
        model.eval()
        y_te = y_te_seq
        with torch.no_grad():
            X_te_t = torch.FloatTensor(X_te_seq).to(device)
            y_prob = model(X_te_t).cpu().numpy()
        y_pred = (y_prob > 0.5).astype(int)

    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    results = {
        "model_name": "lstm",
        "accuracy": round(float(accuracy_score(y_te, y_pred)), 4),
        "precision": round(float(precision_score(y_te, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_te, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_te, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_te, y_prob)), 4) if len(set(y_te)) > 1 else 0.5,
        "profit_factor": 1.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "artifact_path": str(output_dir / "lstm_model.pt"),
    }
    with open(output_dir / "lstm_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"LSTM: accuracy={results['accuracy']} auc={results['auc_roc']} f1={results['f1_score']}")


if __name__ == "__main__":
    main()
