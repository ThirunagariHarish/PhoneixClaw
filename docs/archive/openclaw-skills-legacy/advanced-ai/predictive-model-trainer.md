# Skill: Predictive Model Trainer

## Purpose
Train lightweight predictive models (e.g., price direction, volatility) on historical data for use in signal generation or risk estimation.

## Triggers
- When the agent needs to train or retrain a predictive model
- When user requests model training for a symbol or strategy
- When scheduled retrain (e.g., weekly) is due
- When new data warrants model refresh

## Inputs
- `model_type`: string — "direction", "volatility", "regression", or "classifier"
- `symbol`: string — Ticker for training data
- `features`: string[] — Input features (e.g., ["returns_1d", "volume_ratio", "rsi"])
- `target`: string — Target variable (e.g., "return_1d", "volatility_5d")
- `lookback_days`: number — Training data window (default: 252)
- `hyperparams`: object — Optional model hyperparameters

## Outputs
- `model_id`: string — Trained model identifier
- `metrics`: object — Train/validation accuracy, MSE, or other metrics
- `feature_importance`: object — Per-feature importance if available
- `metadata`: object — Model type, symbol, trained_at, version

## Steps
1. Fetch historical data via market-data-fetcher
2. Compute features (returns, volume, indicators) per feature list
3. Build target variable from price/volatility data
4. Split into train/validation (e.g., 80/20)
5. Train model: sklearn/XGBoost for tabular; simple NN if configured
6. Evaluate on validation set; compute metrics
7. Persist model to model registry with version
8. Return model_id, metrics, feature_importance
9. Log training run for reproducibility

## Example
```
Input: model_type="direction", symbol="NVDA", features=["returns_1d","rsi","volume_ratio"], target="return_1d", lookback_days=252
Output: {
  model_id: "dir_nvda_v1",
  metrics: {accuracy: 0.58, precision: 0.62, recall: 0.55},
  feature_importance: {returns_1d: 0.35, rsi: 0.28, volume_ratio: 0.22},
  metadata: {model_type: "direction", symbol: "NVDA", trained_at: "2025-03-03T15:00:00Z"}
}
```
