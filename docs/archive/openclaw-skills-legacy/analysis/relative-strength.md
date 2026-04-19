# Relative Strength

## Purpose
Compare relative strength between assets (e.g., stock vs sector, stock vs index) to identify outperformance or underperformance for ranking and rotation.

## Category
analysis

## Triggers
- When the agent needs to rank assets by strength
- When user requests relative strength comparison
- When building sector rotation or momentum screens
- When selecting strongest/weakest names in a universe

## Inputs
- `symbol`: string — Primary symbol to evaluate
- `benchmark`: string — Benchmark for comparison (e.g., "SPY", "XLK", "QQQ")
- `lookback_periods`: number — Bars for comparison (default: 20)
- `timeframe`: string — "1d", "1w" for price series (default: "1d")
- `method`: string — "ratio", "spread", or "percentile" (default: ratio)
- `ohlcv`: object[] — Optional pre-fetched bars; if empty, fetch via market-data-fetcher

## Outputs
- `relative_strength`: number — Relative strength value (ratio or spread)
- `rs_percentile`: number — Percentile of current RS in its history (0-100)
- `rs_performance`: number — % change of symbol vs benchmark over lookback
- `rank`: number — Rank in universe if universe provided (1 = strongest)
- `signal`: string — "outperforming", "underperforming", "neutral"
- `metadata`: object — Symbol, benchmark, lookback, computed_at

## Steps
1. Fetch OHLCV for symbol and benchmark if not provided
2. Compute price ratio: symbol_close / benchmark_close (normalized to start)
3. If method=ratio: RS = current ratio; if method=spread: RS = symbol_return - benchmark_return
4. If method=percentile: rank symbol's return vs benchmark's return in historical context
5. Compute rs_percentile: where current RS sits in its own history
6. Compute rs_performance: % return difference over lookback
7. If universe provided, rank all symbols by RS; return rank
8. Derive signal: outperforming (RS > 1 or positive spread), underperforming (RS < 1), neutral
9. Return relative_strength, rs_percentile, rs_performance, rank, signal, metadata
10. Cache results per symbol/benchmark with short TTL

## Example
```
Input: symbol="NVDA", benchmark="XLK", lookback_periods=20, method="ratio"
Output: {
  relative_strength: 1.25,
  rs_percentile: 78,
  rs_performance: 12.5,
  rank: 3,
  signal: "outperforming",
  metadata: {symbol: "NVDA", benchmark: "XLK", lookback: 20, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Ratio method normalizes for scale; spread is in return space
- Use sector benchmark (XLK, XLF) for sector-relative strength
- Combine with momentum for rotation strategies; rank within sector
