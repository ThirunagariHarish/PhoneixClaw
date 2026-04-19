# Advance/Decline Line and Ratio

## Purpose
Compute advance/decline line and A/D ratio for trend confirmation and divergence detection with major indices.

## Category
analysis

## Triggers
- When the agent needs A/D line or ratio for trend analysis
- When user requests advance/decline metrics
- When validating price trend with breadth confirmation
- When detecting market breadth divergence

## Inputs
- `universe`: string — "NYSE", "NASDAQ", "AMEX" (default: NYSE)
- `metric`: string — "line", "ratio", or "both"
- `lookback_days`: number — Days for ratio and line history (default: 50)
- `compare_to`: string — Index to compare against (e.g., "SPY", "QQQ")
- `market_data`: object — Optional pre-fetched A/D data; if empty, fetch via market-data-fetcher

## Outputs
- `ad_line`: number — Current cumulative advance-decline line value
- `ad_line_history`: number[] — Historical A/D line for charting
- `ad_ratio`: number — Advances / Declines (or ratio of volumes)
- `ad_ratio_sma`: number — Simple moving average of A/D ratio
- `divergence`: object — {detected: boolean, type: "bullish"|"bearish"|null, strength: number}
- `metadata`: object — Universe, lookback_days, computed_at

## Steps
1. Fetch daily advance and decline counts for universe if not provided
2. Compute net A/D: advances - declines

3. Compute cumulative A/D line: running sum of net A/D over lookback
4. Compute A/D ratio: advances / declines (or use volume-weighted)
5. Compute A/D ratio SMA for smoothing
6. Fetch price series for compare_to index
7. Compare A/D line slope to index slope; detect divergence if price up but A/D down (or vice versa)
8. Return ad_line, ad_line_history, ad_ratio, ad_ratio_sma
9. Return divergence object if detected
10. Return metadata

## Example
```
Input: universe="NYSE", metric="both", lookback_days=50, compare_to="SPY"
Output: {
  ad_line: 24500,
  ad_line_history: [...],
  ad_ratio: 1.28,
  ad_ratio_sma: 1.1,
  divergence: {detected: false, type: null, strength: 0},
  metadata: {universe: "NYSE", lookback_days: 50, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- A/D line is cumulative; ratio resets daily and can be more volatile
- Divergence detection is heuristic; use multiple confirmation signals
- NYSE A/D includes ETFs; consider pure-equity universe for cleaner signal
