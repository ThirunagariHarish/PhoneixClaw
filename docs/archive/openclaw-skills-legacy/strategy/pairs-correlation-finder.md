# Skill: Pairs Correlation Finder

## Purpose
Identify pairs of symbols with high historical correlation for pairs-trading or spread strategies (cointegration, correlation, spread z-score).

## Triggers
- When the agent needs pairs-trading candidates
- When user requests correlated pairs or spread opportunities
- When building pairs watchlists
- When validating mean-reversion in spreads

## Inputs
- `symbols`: string[] — Universe to test (or sector/industry)
- `metric`: string — "correlation", "cointegration", "spread_zscore"
- `lookback`: number — Days for correlation/cointegration (default: 60)
- `min_correlation`: number — Minimum correlation threshold (default: 0.8)
- `timeframe`: string — "1d" (daily typical for pairs)

## Outputs
- `pairs`: object[] — Top correlated pairs with correlation/cointegration stats
- `spread_zscore`: object — Per-pair spread z-score when metric=spread_zscore
- `metadata`: object — Lookback, symbol count, scan time

## Steps
1. Fetch daily OHLCV for symbols via market-data-fetcher
2. Compute returns for each symbol
3. For correlation: pairwise Pearson correlation matrix
4. For cointegration: Engle-Granger test; filter p-value < 0.05
5. For spread z-score: hedge ratio via OLS, spread = A - ratio*B, z = (spread - mean) / std
6. Rank pairs by correlation strength or cointegration significance
7. Filter by min_correlation or cointegration p-value
8. Return top pairs with stats; include spread z-score if requested
9. Cache results with daily TTL

## Example
```
Input: symbols=["XOM","CVX","COP"], metric="correlation", lookback=60, min_correlation=0.8
Output: {
  pairs: [{symbol_a: "XOM", symbol_b: "CVX", correlation: 0.92}, {symbol_a: "XOM", symbol_b: "COP", correlation: 0.85}],
  spread_zscore: {},
  metadata: {lookback: 60, count: 3, scanned_at: "2025-03-03T15:00:00Z"}
}
```
