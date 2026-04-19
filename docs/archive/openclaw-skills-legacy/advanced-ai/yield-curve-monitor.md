# Yield Curve Monitor

## Purpose
Track 10Y-2Y Treasury spread for recession signals and regime shifts (inversion, steepening, reversion).

## Category
advanced-ai

## Triggers
- When evaluating macro regime or recession risk
- When user requests yield curve status or recession probability
- Periodically (e.g., daily) for regime dashboard
- When adjusting risk or sector exposure based on curve shape

## Inputs
- `yield_data`: object — Optional: {y2y, y10y, y30y} or fetch from bond-yield-fetch
- `lookback_days`: number — Days for trend (default: 30)
- `output_format`: string — "spread", "inversion_status", "full" (default: full)

## Outputs
- `spread_10y_2y`: number — 10Y minus 2Y yield (bps)
- `inverted`: boolean — True if spread < 0
- `trend`: string — "steepening", "flattening", "stable"
- `recession_signal`: string — "elevated", "moderate", "low" based on inversion depth/duration
- `metadata`: object — data_sources, lookback, computed_at

## Steps
1. Fetch 2Y and 10Y Treasury yields (bond-yield-fetch or fred-economic-data)
2. spread_10y_2y = y10y - y2y (in bps or %)
3. inverted = spread_10y_2y < 0
4. trend: compare current spread to lookback avg; steepening = rising, flattening = falling
5. recession_signal: if inverted > 30 days = elevated; inverted < 7 days = moderate; positive = low
6. Return spread_10y_2y, inverted, trend, recession_signal, metadata
7. Cache; refresh on schedule

## Example
```
Input: lookback_days=30, output_format="full"
Output: {
  spread_10y_2y: -45,
  inverted: true,
  trend: "flattening",
  recession_signal: "elevated",
  metadata: {lookback: 30, computed_at: "2025-03-03T15:00:00Z", source: "fred"}
}
```

## Notes
- Inversion historically precedes recession by 6–18 months
- Integrate with macro-regime-detector and yield-curve data skill
- Consider 3M-10Y spread (Fed preferred) as alternative
