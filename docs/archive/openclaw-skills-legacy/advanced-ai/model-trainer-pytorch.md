# Model Trainer PyTorch

## Purpose
Train PyTorch models on market data for neural network-based prediction.

## Category
advanced-ai

## Triggers
- When training LSTM, Transformer, or custom NN
- When sklearn/XGBoost insufficient for sequence data
- When user requests PyTorch model training
- When time-series-forecast needs LSTM model

## Inputs
- `model_type`: string — "lstm", "transformer", "mlp", "custom"
- `symbol`: string — Ticker for data
- `features`: string[] — Input features
- `target`: string — Target variable
- `lookback`: number — Sequence length
- `epochs`: number — Training epochs (default: 100)
- `hyperparams`: object — Learning rate, hidden size, etc.

## Outputs
- `model_id`: string — Trained model identifier
- `metrics`: object — Train/val loss, accuracy
- `checkpoint_path`: string — Model checkpoint path
- `metadata`: object — Model type, symbol, trained_at

## Steps
1. Fetch data via market-data-fetcher
2. Build sequences via ml-feature-engineer
3. Define PyTorch model per model_type
4. Train with validation split
5. Save checkpoint to model registry
6. Return model_id, metrics, checkpoint_path
7. Log training config for reproducibility

## Example
```
Input: model_type="lstm", symbol="NVDA", features=["returns","volume"], target="return_1d", lookback=20, epochs=50
Output: {
  model_id: "lstm_nvda_v1",
  metrics: {train_loss: 0.012, val_loss: 0.015},
  checkpoint_path: "models/lstm_nvda_v1.pt",
  metadata: {model_type: "lstm", symbol: "NVDA", trained_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- GPU acceleration if available
- Early stopping to prevent overfitting
- Integrates with model-inference-runner
