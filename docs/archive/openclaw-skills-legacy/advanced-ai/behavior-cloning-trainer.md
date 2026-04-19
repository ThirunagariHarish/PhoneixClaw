# Behavior Cloning Trainer

## Purpose
Train behavior cloning model from human trading patterns: learn to imitate entry/exit decisions from historical trades and context.

## Category
advanced-ai

## Triggers
- When user has trade history and wants to train an imitation model
- When building agent that mimics a specific trader's style
- When creating synthetic training data for reinforcement learning
- When evaluating consistency of human vs model decisions

## Inputs
- `trade_history`: object[] — [{symbol, side, entry_time, exit_time, entry_price, exit_price, context}]
- `market_context`: object[] — OHLCV, indicators, news at decision times (or fetch)
- `model_type`: string — "mlp", "transformer", "lstm" (default: "mlp")
- `features`: string[] — Features to use (e.g., ["rsi", "macd", "volume_ratio", "sentiment"])
- `train_split`: number — Train/val split (default: 0.8)
- `epochs`: number — Training epochs (default: 50)
- `output_path`: string — Path to save model (default: models/behavior_clone)

## Outputs
- `model_path`: string — Path to saved model
- `metrics`: object — {train_loss, val_loss, train_acc, val_acc}
- `feature_importance`: object — Per-feature contribution (if interpretable)
- `sample_predictions`: object[] — Validation set predictions vs actual
- `metadata`: object — model_type, n_samples, epochs, trained_at

## Steps
1. Load trade_history; align with market_context by timestamp
2. Build feature matrix: extract features at each entry/exit decision point
3. Label: action (buy/sell/hold) or continuous (size, hold_duration)
4. Split into train/val; normalize features
5. Build model: MLP for tabular; LSTM/Transformer for sequence
6. Train with cross-entropy or MSE; early stopping on val_loss
7. Evaluate: accuracy, F1; log sample predictions
8. Save model to output_path; export for inference
9. Return model_path, metrics, feature_importance, sample_predictions, metadata
10. Optionally integrate with reinforcement-learner for fine-tuning

## Example
```
Input: trade_history=[...], model_type="mlp", features=["rsi","macd","volume_ratio"], epochs=50
Output: {
  model_path: "models/behavior_clone/v1.pt",
  metrics: {train_loss: 0.32, val_loss: 0.41, train_acc: 0.78, val_acc: 0.72},
  feature_importance: {rsi: 0.28, macd: 0.35, volume_ratio: 0.22},
  sample_predictions: [{actual: "buy", predicted: "buy", prob: 0.85}, ...],
  metadata: {model_type: "mlp", n_samples: 1200, epochs: 50, trained_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Behavior cloning suffers from distribution shift; consider DAgger or online fine-tuning
- More data improves generalization; aim for 500+ trades
- Use model-inference-runner for live inference after training
