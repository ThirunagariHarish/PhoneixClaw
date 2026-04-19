# Skill: Momentum Tracker

## Purpose
Track and rank symbols by momentum strength (e.g., ROC, relative strength vs index) to identify trending candidates for momentum-based strategies.

## Triggers
- When the agent needs momentum rankings or trend strength
- When user requests momentum plays or strongest movers
- When building momentum-based watchlists
- When validating trend-following entries

## Inputs
- `symbols`: string[] — Tickers to evaluate
- `metric`: string — "roc", "relative_strength", "adx", or "composite"
- `period`: number — Lookback for ROC/RS (default: 20)
- `benchmark`: string — Index for relative strength (e.g., "SPY", "QQQ")
- `timeframe`: string — "1h", "1d"

## Outputs
- `ranked`: object[] — Symbols sorted by momentum strength (strongest first)
- `scores`: object — Per-symbol momentum values
- `trend_direction`: object — "up", "down", "neutral" per symbol
- `metadata`: object — Scan time, benchmark, period

## Steps
1. Fetch price data for symbols and benchmark via market-data-fetcher
2. For ROC: (close - close_n_periods_ago) / close_n_periods_ago * 100
3. For relative strength: symbol_return / benchmark_return over period
4. For ADX: compute +DI, -DI, ADX from high/low/close
5. Rank symbols by chosen metric (descending for bullish momentum)
6. Assign trend_direction based on threshold (e.g., ROC > 5% = up)
7. Return ranked list, scores, and trend directions
8. Cache results with short TTL

## Example
```
Input: symbols=["AAPL","NVDA","META"], metric="roc", period=20, timeframe="1d"
Output: {
  ranked: [{symbol: "NVDA", roc: 12.5}, {symbol: "META", roc: 8.2}, {symbol: "AAPL", roc: 2.1}],
  scores: {AAPL: 2.1, NVDA: 12.5, META: 8.2},
  trend_direction: {AAPL: "neutral", NVDA: "up", META: "up"},
  metadata: {scanned_at: "2025-03-03T15:00:00Z"}
}
```
