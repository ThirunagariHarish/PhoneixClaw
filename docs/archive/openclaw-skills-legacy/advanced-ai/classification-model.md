# Classification Model

## Purpose
Classify market conditions (bull/bear/sideways) for regime-aware trading.

## Category
advanced-ai

## Triggers
- When determining current market regime
- When strategy needs regime filter
- When user requests market condition assessment
- When switching strategy parameters by regime

## Inputs
- `model_id`: string — Trained classifier identifier
- `features`: object — Feature vector
- `symbol`: string — Symbol or index (e.g., "SPY")
- `classes`: string[] — Expected classes (e.g., ["bull","bear","sideways"])

## Outputs
- `prediction`: string — Predicted class
- `probabilities`: object — Class probabilities
- `confidence`: number — Max probability
- `metadata`: object — Model_id, symbol, timestamp

## Steps
1. Load classifier by model_id
2. Validate features match training schema
3. Run inference; get class and probabilities
4. Return prediction, probabilities, confidence
5. Log for regime tracking over time

## Example
```
Input: model_id="regime_spy_v1", features={trend_strength: 0.7, volatility: 0.15}, symbol="SPY"
Output: {
  prediction: "bull",
  probabilities: {bull: 0.72, bear: 0.15, sideways: 0.13},
  confidence: 0.72,
  metadata: {model_id: "regime_spy_v1", symbol: "SPY"}
}
```

## Notes
- Supports binary and multiclass
- Threshold tuning for class imbalance
- Integrates with strategy parameter selection
