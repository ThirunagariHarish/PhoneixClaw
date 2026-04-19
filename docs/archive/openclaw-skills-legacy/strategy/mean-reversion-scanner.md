# Skill: Mean Reversion Scanner

## Purpose
Identify symbols trading significantly away from their mean (e.g., Bollinger Band extremes, z-score deviations) for potential mean-reversion entry opportunities.

## Triggers
- When the agent needs to find oversold/overbought candidates
- When user requests mean-reversion setups or pullback plays
- When building a watchlist of reversion candidates
- When validating entries against statistical extremes

## Inputs
- `symbols`: string[] — Tickers to scan (or universe from config)
- `metric`: string — "bb_percent", "z_score", "rsi", or "composite"
- `threshold`: number — Deviation threshold (e.g., z > 2 or BB% < -2)
- `timeframe`: string — "5m", "15m", "1h", "1d"
- `lookback`: number — Periods for mean/std calculation (default: 20)

## Outputs
- `oversold`: object[] — Symbols below lower threshold with metadata
- `overbought`: object[] — Symbols above upper threshold with metadata
- `scores`: object — Per-symbol deviation scores
- `metadata`: object — Scan time, symbol count, thresholds used

## Steps
1. Fetch OHLCV for symbols via market-data-fetcher
2. Compute chosen metric: BB%, z-score, or RSI
3. For BB%: (price - lower_band) / (upper - lower) * 100; <0 oversold, >100 overbought
4. For z-score: (price - SMA) / std; <-2 oversold, >2 overbought
5. Filter symbols meeting threshold criteria
6. Rank by severity of deviation (most extreme first)
7. Attach metadata: symbol, metric value, price, timestamp
8. Return oversold, overbought lists and scores
9. Cache scan results with short TTL

## Example
```
Input: symbols=["AAPL","NVDA","TSLA"], metric="z_score", threshold=2, timeframe="15m"
Output: {
  oversold: [{symbol: "TSLA", z_score: -2.3, price: 245.50}],
  overbought: [{symbol: "NVDA", z_score: 2.1, price: 890.20}],
  scores: {AAPL: 0.5, NVDA: 2.1, TSLA: -2.3},
  metadata: {scanned_at: "2025-03-03T15:00:00Z", count: 3}
}
```
