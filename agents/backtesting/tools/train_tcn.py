"""Train Temporal Convolutional Network (TCN) for trade prediction.

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
        print("PyTorch not available — skipping TCN training")
        _write_skip_result(output_dir, "PyTorch not installed")
        return

    warnings.filterwarnings("ignore")
    device = torch.device("cpu")

    X_train = np.load(data_dir / "X_train.npy", mmap_mode="r").astype(np.float32)
    X_val = np.load(data_dir / "X_val.npy", mmap_mode="r").astype(np.float32)
    X_test = np.load(data_dir / "X_test.npy", mmap_mode="r").astype(np.float32)
    y_train = np.load(data_dir / "y_train.npy").astype(np.float32)
    y_val = np.load(data_dir / "y_val.npy").astype(np.float32)
    y_test = np.load(data_dir / "y_test.npy").astype(np.float32)

    candle_train = np.load(data_dir / "candle_train.npy", mmap_mode="r").astype(np.float32) \
        if (data_dir / "candle_train.npy").exists() else None
    candle_val = np.load(data_dir / "candle_val.npy", mmap_mode="r").astype(np.float32) \
        if (data_dir / "candle_val.npy").exists() else None
    candle_test = np.load(data_dir / "candle_test.npy", mmap_mode="r").astype(np.float32) \
        if (data_dir / "candle_test.npy").exists() else None

    use_candles = candle_train is not None and candle_val is not None

    if use_candles:
        seq_len = candle_train.shape[1]
        n_channels = candle_train.shape[2]
        tab_dim = X_train.shape[1]
        print(f"TCN with candles: seq={seq_len}, channels={n_channels}, tabular={tab_dim}")
    else:
        SEQ_LEN = 10
        tab_dim = X_train.shape[1]
        n_channels = tab_dim

        def _make_sequences(X, y, seq_len):
            if len(X) <= seq_len:
                seqs = np.expand_dims(X, 0) if len(X) > 0 else np.zeros((1, seq_len, X.shape[1]))
                labels = np.array([y[-1]]) if len(y) > 0 else np.array([0])
                return seqs.astype(np.float32), labels.astype(np.float32)
            seqs, labels = [], []
            for i in range(seq_len, len(X)):
                seqs.append(X[i - seq_len:i])
                labels.append(y[i])
            return np.array(seqs, dtype=np.float32), np.array(labels, dtype=np.float32)

        candle_train, y_train = _make_sequences(X_train, y_train, SEQ_LEN)
        candle_val, y_val = _make_sequences(X_val, y_val, SEQ_LEN)
        candle_test, y_test = _make_sequences(X_test, y_test, SEQ_LEN)
        seq_len = SEQ_LEN
        X_train = X_train[SEQ_LEN:]
        X_val = X_val[SEQ_LEN:]
        X_test = X_test[SEQ_LEN:]
        use_candles = True
        tab_dim = X_train.shape[1] if len(X_train) > 0 else tab_dim
        print(f"TCN with tabular sequences: seq={seq_len}, features={n_channels}")

    HIDDEN = 64

    class TemporalBlock(nn.Module):
        def __init__(self, in_ch, out_ch, kernel_size, dilation, dropout=0.2):
            super().__init__()
            padding = (kernel_size - 1) * dilation
            self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
            self.bn1 = nn.BatchNorm1d(out_ch)
            self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size, padding=padding, dilation=dilation)
            self.bn2 = nn.BatchNorm1d(out_ch)
            self.drop = nn.Dropout(dropout)
            self.relu = nn.ReLU()
            self.downsample = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

        def forward(self, x):
            residual = self.downsample(x)
            out = self.relu(self.bn1(self.conv1(x)[:, :, :x.size(2)]))
            out = self.drop(out)
            out = self.relu(self.bn2(self.conv2(out)[:, :, :x.size(2)]))
            out = self.drop(out)
            return self.relu(out + residual)

    class TCNClassifier(nn.Module):
        def __init__(self, n_channels, hidden, tab_dim, n_blocks=3, kernel_size=3, dropout=0.3):
            super().__init__()
            blocks = []
            ch = n_channels
            for i in range(n_blocks):
                blocks.append(TemporalBlock(ch, hidden, kernel_size, 2 ** i, dropout))
                ch = hidden
            self.tcn = nn.Sequential(*blocks)
            self.tab_proj = nn.Sequential(
                nn.Linear(tab_dim, 32), nn.ReLU(), nn.Dropout(0.2)
            ) if tab_dim > 0 else None
            cls_in = hidden + (32 if tab_dim > 0 else 0)
            self.classifier = nn.Sequential(
                nn.Linear(cls_in, 48), nn.ReLU(), nn.Dropout(dropout),
                nn.Linear(48, 1), nn.Sigmoid(),
            )

        def forward(self, seq, tab=None):
            x = seq.permute(0, 2, 1)
            x = self.tcn(x)
            x = x.mean(dim=2)
            if self.tab_proj is not None and tab is not None:
                t = self.tab_proj(tab)
                x = torch.cat([x, t], dim=1)
            return self.classifier(x).squeeze(-1)

    model = TCNClassifier(n_channels, hidden=HIDDEN, tab_dim=tab_dim, n_blocks=3, kernel_size=3, dropout=0.3).to(device)

    min_len = min(len(candle_train), len(X_train), len(y_train))
    ct_np = candle_train[:min_len].copy() if hasattr(candle_train, 'copy') else candle_train[:min_len]
    xt_np = X_train[:min_len].copy() if hasattr(X_train, 'copy') else X_train[:min_len]
    yt_np = y_train[:min_len]

    min_vlen = min(len(candle_val), len(X_val), len(y_val))
    cv_np = candle_val[:min_vlen].copy() if hasattr(candle_val, 'copy') else candle_val[:min_vlen]
    xv_np = X_val[:min_vlen].copy() if hasattr(X_val, 'copy') else X_val[:min_vlen]
    yv_np = y_val[:min_vlen]

    del candle_train, candle_val
    _cleanup()

    ct = torch.from_numpy(ct_np)
    xt = torch.from_numpy(xt_np)
    yt = torch.FloatTensor(yt_np)
    cv = torch.from_numpy(cv_np)
    xv = torch.from_numpy(xv_np)
    yv = torch.FloatTensor(yv_np)

    del ct_np, xt_np, yt_np, cv_np, xv_np, yv_np
    _cleanup()

    batch_size = min(32, len(ct))
    train_ds = TensorDataset(ct, xt, yt)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=len(ct) > batch_size)

    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)

    best_val_loss = float("inf")
    patience_counter = 0
    patience = 12
    epochs = 80

    print(f"Training TCN: {sum(p.numel() for p in model.parameters())} params, {len(ct)} train, {len(cv)} val")

    for epoch in range(epochs):
        model.train()
        train_loss = 0
        for batch_c, batch_x, batch_y in train_loader:
            optimizer.zero_grad()
            preds = model(batch_c, batch_x)
            loss = criterion(preds, batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()

        model.eval()
        with torch.no_grad():
            val_preds = model(cv, xv)
            val_loss = criterion(val_preds, yv).item()

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), output_dir / "tcn_model.pt")
        else:
            patience_counter += 1

        if (epoch + 1) % 10 == 0:
            print(f"  Epoch {epoch+1}: train_loss={train_loss/len(train_loader):.4f}, val_loss={val_loss:.4f}")

        if patience_counter >= patience:
            print(f"  Early stopping at epoch {epoch+1}")
            break

    model.load_state_dict(torch.load(output_dir / "tcn_model.pt", weights_only=True))
    model.eval()

    del ct, xt, yt, cv, xv, yv, train_ds, train_loader
    _cleanup()

    if candle_test is not None and len(candle_test) > 0 and len(X_test) > 0:
        min_tlen = min(len(candle_test), len(X_test), len(y_test))
        cte_np = candle_test[:min_tlen].copy() if hasattr(candle_test, 'copy') else candle_test[:min_tlen]
        xte_np = X_test[:min_tlen].copy() if hasattr(X_test, 'copy') else X_test[:min_tlen]
        yte = y_test[:min_tlen]

        del candle_test
        _cleanup()

        with torch.no_grad():
            test_proba = model(torch.from_numpy(cte_np), torch.from_numpy(xte_np)).numpy()
        test_preds = (test_proba >= 0.5).astype(int)

        del cte_np, xte_np
        _cleanup()

        from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
        acc = accuracy_score(yte, test_preds)
        try:
            auc = roc_auc_score(yte, test_proba)
        except ValueError:
            auc = 0.5
        report = classification_report(yte, test_preds, output_dict=True, zero_division=0)

        np.save(output_dir / "tcn_test_proba.npy", test_proba)
    else:
        acc, auc, report = 0.5, 0.5, {}

    results = {
        "model_name": "tcn",
        "accuracy": round(acc, 4),
        "auc_roc": round(auc, 4),
        "precision": round(report.get("1", {}).get("precision", 0), 4),
        "recall": round(report.get("1", {}).get("recall", 0), 4),
        "f1": round(report.get("1", {}).get("f1-score", 0), 4),
        "val_loss": round(best_val_loss, 4),
        "model_artifact": "tcn_model.pt",
    }
    try:
        from compute_trading_metrics import compute_trading_metrics
        if len(test_proba) > 0:
            results.update(compute_trading_metrics(
                data_dir, np.asarray(test_proba).reshape(-1), threshold=0.55
            ))
        else:
            results.setdefault("sharpe_ratio", 0.0)
            results.setdefault("max_drawdown_pct", 0.0)
            results.setdefault("profit_factor", 1.0)
    except Exception as exc:
        print(f"  [train_tcn] trading metrics computation failed: {exc}")
        results.setdefault("sharpe_ratio", 0.0)
        results.setdefault("max_drawdown_pct", 0.0)
        results.setdefault("profit_factor", 1.0)

    with open(output_dir / "tcn_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"TCN results: accuracy={acc:.4f}, AUC={auc:.4f}")

    try:
        from report_to_phoenix import report_progress
        report_progress("train_tcn", f"TCN trained: accuracy={acc:.4f} auc={auc:.4f}", 55, results)
    except Exception:
        pass


def _write_skip_result(output_dir, reason):
    results = {
        "model_name": "tcn",
        "accuracy": 0.0, "auc_roc": 0.0,
        "precision": 0.0, "recall": 0.0, "f1": 0.0,
        "skipped": True, "skip_reason": reason,
        "profit_factor": 1.0, "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0,
    }
    with open(output_dir / "tcn_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
