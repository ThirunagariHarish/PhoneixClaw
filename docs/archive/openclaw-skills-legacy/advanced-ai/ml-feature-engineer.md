# ML Feature Engineer

## Purpose
Engineer ML features from market data for model training and signal generation.

## Category
advanced-ai

## Triggers
- Before training predictive models
- When new feature sets are needed for strategies
- When user requests feature computation
- When backtesting requires custom features

## Inputs
- `symbol`: string — Ticker for data
- `data`: object — OHLCV or raw market data
- `feature_set`: string[] — Feature names (e.g., "returns", "rsi", "volatility")
- `lookback`: number — Bars for rolling features (default: 20)
- `normalize`: boolean — Z-score or min-max normalize (default: false)

## Outputs
- `features`: object — Computed feature matrix
- `feature_names`: string[] — Ordered feature names
- `metadata`: object — Symbol, date range, feature_set
- `schema`: object — Feature types and valid ranges

## Steps
1. Load or receive OHLCV data
2. Compute base features (returns, volume ratio, etc.)
3. Add technical indicators per feature_set (RSI, MACD, Bollinger)
4. Compute rolling stats (mean, std, min, max)
5. Optionally normalize features
6. Return feature matrix with schema
7. Cache for reuse in same session

## Example
```
Input: symbol="AAPL", feature_set=["returns_1d","rsi","volume_ratio"], lookback=14
Output: {
  features: {returns_1d: [...], rsi: [...], volume_ratio: [...]},
  feature_names: ["returns_1d","rsi","volume_ratio"],
  metadata: {symbol: "AAPL", bars: 252},
  schema: {returns_1d: "float", rsi: "float", volume_ratio: "float"}
}
```

## Notes
- Handles missing data (forward fill or drop)
- Supports custom feature definitions via config
- Integrates with predictive-model-trainer
