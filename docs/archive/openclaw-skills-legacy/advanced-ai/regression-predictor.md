# Regression Predictor

## Purpose
Run regression predictions on price data for target estimation (returns, volatility).

## Category
advanced-ai

## Triggers
- When predicting next-period returns
- When estimating volatility for risk
- When user requests regression forecast
- When strategy needs continuous target

## Inputs
- `model_id`: string — Trained regression model identifier
- `features`: object — Feature vector or matrix
- `symbol`: string — Symbol (for model lookup if needed)
- `horizon`: number — Prediction horizon in bars (default: 1)

## Outputs
- `prediction`: number — Predicted value
- `confidence_interval`: object — Lower/upper bounds if available
- `metadata`: object — Model_id, symbol, timestamp
- `feature_importance`: object — Contribution per feature (optional)

## Steps
1. Load model by model_id
2. Validate feature schema matches model
3. Run inference on features
4. Compute confidence interval if model supports it
5. Return prediction and metadata
6. Log prediction for tracking

## Example
```
Input: model_id="ret_nvda_v1", features={returns_1d: 0.02, rsi: 55, volume_ratio: 1.2}, symbol="NVDA"
Output: {
  prediction: 0.015,
  confidence_interval: {lower: 0.005, upper: 0.025},
  metadata: {model_id: "ret_nvda_v1", symbol: "NVDA"},
  feature_importance: {returns_1d: 0.6, rsi: 0.2, volume_ratio: 0.2}
}
```

## Notes
- Model must be trained with predictive-model-trainer or model-trainer-pytorch
- Supports sklearn, XGBoost, and custom regressors
- Horizon > 1 may require recursive prediction
