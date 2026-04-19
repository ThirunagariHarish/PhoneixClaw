# Parabolic SAR Trailing

## Purpose
Parabolic SAR for optimal stop-loss placement and trend reversal detection.

## Category
analysis

## Triggers
- When user requests SAR levels for stop-loss or trailing stop
- When building trend-following exit logic
- When assessing trend reversal points
- When overlaying SAR on charts for visualization

## Inputs
- `symbol`: string — Ticker to analyze
- `ohlcv`: object[] — OHLCV bars (or fetch)
- `acceleration`: number — SAR acceleration factor (default: 0.02)
- `maximum`: number — Max acceleration cap (default: 0.2)
- `include_stops`: boolean — Return suggested stop levels (default: true)
- `lookback_bars`: number — Bars for SAR calc (default: 100)

## Outputs
- `sar_value`: number — Current Parabolic SAR level
- `trend`: string — "bullish", "bearish"
- `stop_level`: number — Suggested stop-loss (SAR value)
- `reversal_bar`: number — Bar index of last SAR reversal (if recent)
- `sar_series`: number[] — SAR values for chart overlay (optional)
- `metadata`: object — symbol, acceleration, maximum, computed_at

## Steps
1. Fetch or accept OHLCV; initialize SAR: first bar low (bullish) or high (bearish)
2. For each bar: SAR = prior SAR + AF * (EP - prior SAR); AF increases on new EP
3. Bullish: EP = highest high; bearish: EP = lowest low
4. Reversal: price crosses SAR; flip trend, reset AF, set new EP
5. Cap AF at maximum
6. sar_value = current bar SAR; trend from current state
7. stop_level = sar_value for trailing stop
8. reversal_bar = bar index of last flip (for recent reversal detection)
9. Return sar_value, trend, stop_level, reversal_bar, sar_series, metadata
10. Cache with 15m TTL

## Example
```
Input: symbol="AAPL", acceleration=0.02, maximum=0.2
Output: {
  sar_value: 178.45,
  trend: "bullish",
  stop_level: 178.45,
  reversal_bar: 85,
  sar_series: [175.2, 176.1, 177.0, 178.45],
  metadata: {symbol: "AAPL", acceleration: 0.02, maximum: 0.2, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- SAR works best in trending markets; combine with adx-trend-strength
- Use dynamic-stop-atr for ATR-based alternative
- Stop_level updates each bar; suitable for trailing stop logic
