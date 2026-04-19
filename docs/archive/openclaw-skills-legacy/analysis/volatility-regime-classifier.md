# Volatility Regime Classifier

## Purpose
Classify volatility regime (low/normal/high/extreme) from VIX term structure and level for strategy and sizing adjustments.

## Category
analysis

## API Integration
- Consumes: VIX, VIX term structure (VIX9D, VIX, VIX3M) from market data; treasury-yield-curve for context; No direct API

## Triggers
- When agent needs volatility regime classification
- When user requests VIX regime, vol environment, or term structure
- When adjusting position size or strategy for vol regime
- When assessing if vol is elevated or suppressed

## Inputs
- `vix`: number — Current VIX level
- `vix_term`: object — {VIX9D, VIX, VIX3M} or similar
- `vix_history`: number[] — Prior VIX values for percentile (optional)
- `lookback_days`: number — For percentile calc (default: 252)

## Outputs
- `regime`: string — "low", "normal", "high", "extreme"
- `vix_percentile`: number — Current VIX vs history (0-100)
- `term_structure`: string — "contango", "backwardation", "flat"
- `term_slope`: number — VIX3M - VIX (positive = contango)
- `metadata`: object — VIX, regime, computed_at

## Steps
1. Get current VIX and term structure (VIX9D, VIX, VIX3M)
2. Compute vix_percentile from vix_history (or use typical bands)
3. Regime: low (VIX<12), normal (12-20), high (20-30), extreme (>30)
4. Term structure: contango (VIX3M > VIX), backwardation (VIX3M < VIX)
5. term_slope = VIX3M - VIX
6. Return regime, percentile, term_structure, slope
7. Cache with 15m TTL; VIX updates frequently

## Example
```
Input: vix=14.5, vix_term={VIX9D:14.2, VIX:14.5, VIX3M:16.0}
Output: {
  regime: "normal",
  vix_percentile: 35,
  term_structure: "contango",
  term_slope: 1.5,
  metadata: {vix:14.5, regime:"normal", computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- Backwardation often precedes vol spikes (fear)
- Contango normal in calm markets
- Extreme regime: reduce size, consider vol-selling strategies
