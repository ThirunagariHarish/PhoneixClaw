# Model Inference Runner

## Purpose
Run inference on trained models (sklearn, PyTorch, XGBoost) for predictions.

## Category
advanced-ai

## Triggers
- When strategy needs model prediction
- When user requests inference
- When regression-predictor or classification-model delegates
- When batch prediction for multiple symbols

## Inputs
- `model_id`: string — Trained model identifier
- `inputs`: object — Feature vector or batch
- `model_framework`: string — "sklearn", "pytorch", "xgboost"
- `device`: string — "cpu" or "cuda" (for PyTorch)
- `batch_size`: number — Batch size for large inputs (optional)

## Outputs
- `predictions`: number[] or string[] — Model outputs
- `latency_ms`: number — Inference time in ms
- `metadata`: object — Model_id, framework, batch_size
- `probabilities`: object — Class probabilities (for classifiers)

## Steps
1. Load model from registry by model_id
2. Validate input shape/schema
3. Run inference (single or batch)
4. Post-process (argmax for classification, etc.)
5. Return predictions and latency
6. Cache model in memory for repeated calls

## Example
```
Input: model_id="lstm_nvda_v1", inputs={features: [[...]]}, model_framework="pytorch", device="cpu"
Output: {
  predictions: [0.015, 0.018, 0.012],
  latency_ms: 12,
  metadata: {model_id: "lstm_nvda_v1", framework: "pytorch"},
  probabilities: null
}
```

## Notes
- Supports multiple frameworks via adapter pattern
- Batch inference for efficiency
- Used by regression-predictor, classification-model, time-series-forecast
