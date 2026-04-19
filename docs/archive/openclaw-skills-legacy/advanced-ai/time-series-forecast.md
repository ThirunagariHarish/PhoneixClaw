# Time Series Forecast

## Purpose
Time series forecasting with LSTM, Prophet, or ARIMA for price/volatility prediction.

## Category
advanced-ai

## Triggers
- When multi-step price forecast is needed
- When projecting volatility for risk
- When strategy requires horizon > 1 bar
- When user requests time series prediction

## Inputs
- `model_id`: string — Trained model identifier
- `series`: number[] — Input time series (or symbol for data fetch)
- `horizon`: number — Forecast steps ahead
- `model_type`: string — "lstm", "prophet", "arima"
- `confidence_level`: number — Confidence interval (default: 0.95)

## Outputs
- `forecast`: number[] — Point forecasts
- `lower`: number[] — Lower bound of interval
- `upper`: number[] — Upper bound of interval
- `metadata`: object — Model_id, horizon, model_type

## Steps
1. Load model by model_id or fit on fly for ARIMA/Prophet
2. Prepare series (normalize, handle missing)
3. Run forecast for horizon steps
4. Compute confidence intervals if supported
5. Return forecast, lower, upper
6. Cache for repeated horizons

## Example
```
Input: model_id="lstm_aapl_v1", series=[...], horizon=5, model_type="lstm"
Output: {
  forecast: [178.5, 179.2, 178.8, 180.1, 181.0],
  lower: [176.0, 176.5, 176.0, 177.5, 178.0],
  upper: [181.0, 182.0, 181.5, 182.5, 184.0],
  metadata: {model_id: "lstm_aapl_v1", horizon: 5}
}
```

## Notes
- LSTM requires sequence length matching training
- Prophet handles seasonality and holidays
- ARIMA for stationary series
