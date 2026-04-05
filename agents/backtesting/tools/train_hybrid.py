"""Train hybrid ensemble model: LSTM candle encoder + text + tabular fusion."""

import argparse
import json
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
    X_test = np.load(data_dir / "X_test.npy")
    y_train = np.load(data_dir / "y_train.npy")
    y_test = np.load(data_dir / "y_test.npy")

    candle_train = np.load(data_dir / "candle_train.npy") if (data_dir / "candle_train.npy").exists() else None
    candle_test = np.load(data_dir / "candle_test.npy") if (data_dir / "candle_test.npy").exists() else None
    text_train = np.load(data_dir / "text_train.npy") if (data_dir / "text_train.npy").exists() else None
    text_test = np.load(data_dir / "text_test.npy") if (data_dir / "text_test.npy").exists() else None

    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        print("PyTorch not available, skipping Hybrid training")
        results = {"model_name": "hybrid", "accuracy": 0, "error": "pytorch not installed"}
        with open(output_dir / "hybrid_results.json", "w") as f:
            json.dump(results, f, indent=2)
        return

    has_candles = candle_train is not None
    has_text = text_train is not None

    if not has_candles:
        # Use zeros for candle input
        candle_train_t = np.zeros((len(X_train), 30, 15), dtype=np.float32)
        candle_test_t = np.zeros((len(X_test), 30, 15), dtype=np.float32)
    else:
        candle_train_t = candle_train
        candle_test_t = candle_test

    if not has_text:
        text_train_t = np.zeros((len(X_train), 384), dtype=np.float32)
        text_test_t = np.zeros((len(X_test), 384), dtype=np.float32)
    else:
        text_train_t = text_train
        text_test_t = text_test

    candle_features = candle_train_t.shape[2]
    text_dim = text_train_t.shape[1]
    tabular_dim = X_train.shape[1]

    class HybridEnsemble(nn.Module):
        def __init__(self, tab_dim, txt_dim, candle_feat, seq_len=30):
            super().__init__()
            self.candle_encoder = nn.LSTM(candle_feat, 64, num_layers=2, batch_first=True, dropout=0.3)
            self.text_proj = nn.Sequential(nn.Linear(txt_dim, 64), nn.ReLU())
            self.tab_proj = nn.Sequential(nn.Linear(tab_dim, 64), nn.ReLU())
            self.fusion = nn.Sequential(
                nn.Linear(192, 128), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.2),
                nn.Linear(64, 1), nn.Sigmoid()
            )

        def forward(self, candle_seq, text_emb, tabular):
            _, (h_candle, _) = self.candle_encoder(candle_seq)
            h_text = self.text_proj(text_emb)
            h_tab = self.tab_proj(tabular)
            fused = torch.cat([h_candle[-1], h_text, h_tab], dim=1)
            return self.fusion(fused).squeeze(-1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = HybridEnsemble(tabular_dim, text_dim, candle_features).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=5e-4, weight_decay=1e-5)
    criterion = nn.BCELoss()

    n = len(X_train)
    val_split = int(n * 0.85)

    train_ds = TensorDataset(
        torch.FloatTensor(candle_train_t[:val_split]),
        torch.FloatTensor(text_train_t[:val_split]),
        torch.FloatTensor(X_train[:val_split]),
        torch.FloatTensor(y_train[:val_split]),
    )
    train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)

    c_vl = torch.FloatTensor(candle_train_t[val_split:]).to(device)
    t_vl = torch.FloatTensor(text_train_t[val_split:]).to(device)
    x_vl = torch.FloatTensor(X_train[val_split:]).to(device)
    y_vl = torch.FloatTensor(y_train[val_split:]).to(device)

    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(100):
        model.train()
        for cb, tb_text, tb_tab, yb in train_dl:
            cb, tb_text, tb_tab, yb = cb.to(device), tb_text.to(device), tb_tab.to(device), yb.to(device)
            loss = criterion(model(cb, tb_text, tb_tab), yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss = criterion(model(c_vl, t_vl, x_vl), y_vl).item()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), output_dir / "hybrid_model.pt")
        else:
            patience_counter += 1
            if patience_counter >= 15:
                break

    model.load_state_dict(torch.load(output_dir / "hybrid_model.pt", weights_only=True))
    model.eval()
    with torch.no_grad():
        y_prob = model(
            torch.FloatTensor(candle_test_t).to(device),
            torch.FloatTensor(text_test_t).to(device),
            torch.FloatTensor(X_test).to(device),
        ).cpu().numpy()
        y_pred = (y_prob > 0.5).astype(int)

    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
    results = {
        "model_name": "hybrid",
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 4) if len(set(y_test)) > 1 else 0.5,
        "profit_factor": 1.0, "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0,
        "artifact_path": str(output_dir / "hybrid_model.pt"),
    }
    with open(output_dir / "hybrid_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"Hybrid: accuracy={results['accuracy']} auc={results['auc_roc']}")


if __name__ == "__main__":
    main()
