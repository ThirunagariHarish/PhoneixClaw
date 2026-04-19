# Bollinger Squeeze Detector

## Purpose
Detect Bollinger Band squeeze (low volatility preceding breakout) for momentum or mean-reversion setups.

## Category
analysis

## Triggers
- When user requests squeeze detection for a symbol
- When screening for low-volatility breakout candidates
- When building volatility expansion signals
- When assessing pre-breakout conditions

## Inputs
- `symbol`: string — Ticker to analyze
- `ohlcv`: object[] — OHLCV bars (or fetch)
- `bb_period`: number — Bollinger Band period (default: 20)
- `bb_std`: number — Standard deviation multiplier (default: 2)
- `squeeze_lookback`: number — Bars to define squeeze (default: 20)
- `squeeze_threshold`: number — Band width percentile for squeeze (default: 0.2)

## Outputs
- `in_squeeze`: boolean — True if currently in squeeze
- `squeeze_strength`: number — 0–1, how tight bands are vs history
- `band_width`: number — Current BB width (upper - lower) / middle
- `band_width_percentile`: number — Current width vs historical (0–100)
- `breakout_direction`: string — "bullish", "bearish", "none" (if breakout detected)
- `metadata`: object — symbol, period, computed_at

## Steps
1. Fetch or accept OHLCV; compute SMA(close, bb_period)
2. Compute upper = SMA + bb_std * std(close), lower = SMA - bb_std * std(close)
3. band_width = (upper - lower) / middle
4. band_width_percentile = percentile rank of current width over lookback
5. in_squeeze = band_width_percentile <= squeeze_threshold * 100
6. squeeze_strength = 1 - (band_width_percentile / 100)
7. If breakout: compare close vs bands; breakout_direction from band touch
8. Return in_squeeze, squeeze_strength, band_width, band_width_percentile, breakout_direction, metadata
9. Cache with 15m TTL

## Example
```
Input: symbol="SPY", bb_period=20, squeeze_threshold=0.2
Output: {
  in_squeeze: true,
  squeeze_strength: 0.85,
  band_width: 0.018,
  band_width_percentile: 12,
  breakout_direction: "none",
  metadata: {symbol: "SPY", period: 20, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Squeeze often precedes large moves; combine with volume for confirmation
- Use volatility-regime-classifier for broader vol context
- Consider momentum filter (e.g., ADX) to avoid false breakouts
