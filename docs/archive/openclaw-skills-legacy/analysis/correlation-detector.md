# Skill: Correlation Detector

## Purpose
Detect correlations between assets (stocks, ETFs, indices) to assess diversification, hedge effectiveness, and portfolio concentration risk.

## Triggers
- When the agent needs correlation between symbols for portfolio construction
- When user requests correlation analysis or diversification check
- When building multi-asset strategies or hedged portfolios
- When position-exposure-checker needs correlation input

## Inputs
- `symbols`: string[] — Tickers to correlate (2 or more)
- `benchmark`: string — Optional benchmark (e.g., "SPY") for correlation to market
- `lookback_days`: number — Days of returns for correlation (default: 60)
- `method`: string — "pearson", "spearman", or "rolling" (rolling window)

## Outputs
- `correlation_matrix`: object — Pairwise correlations (symbol1_symbol2: value)
- `correlation_to_benchmark`: object — Per-symbol correlation to benchmark
- `warnings`: string[] — High correlation pairs (>0.8) for diversification
- `metadata`: object — Lookback, method, computed_at

## Steps
1. Fetch daily returns for each symbol via market-data-fetcher (1d bars)
2. Align dates: use common trading days, forward-fill or drop missing
3. Compute returns: (close - prev_close) / prev_close
4. For each pair, compute correlation: Pearson (linear) or Spearman (rank)
5. Build correlation_matrix: { "AAPL_NVDA": 0.72, "AAPL_MSFT": 0.85, ... }
6. If benchmark: compute each symbol's correlation to benchmark returns
7. Identify high correlation pairs (e.g., >0.8): add to warnings
8. For rolling: compute correlation over sliding window; return time series if requested
9. Return correlation_matrix, correlation_to_benchmark, warnings, metadata
10. Cache matrix per symbol set and lookback to reduce recomputation

## Example
```
Input: symbols=["AAPL", "NVDA", "MSFT"], benchmark="SPY", lookback_days=60
Output: {
  correlation_matrix: {AAPL_NVDA: 0.68, AAPL_MSFT: 0.82, NVDA_MSFT: 0.71},
  correlation_to_benchmark: {AAPL: 0.75, NVDA: 0.62, MSFT: 0.78},
  warnings: ["AAPL and MSFT highly correlated (0.82) - consider diversification"],
  metadata: {lookback_days: 60, method: "pearson", computed_at: "2025-03-03T15:00:00Z"}
}
```
