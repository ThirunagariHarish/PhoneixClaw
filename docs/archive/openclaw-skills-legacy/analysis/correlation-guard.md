# Correlation Guard

## Purpose
Cross-asset correlation analysis (SPY/QQQ, sector leaders, USD/JPY) for diversification, hedging, and regime detection.

## Category
analysis

## API Integration
- Consumes: Price data from ibkr-historical-bars, polygon-snapshot, or similar; No direct API; Computes correlation matrix

## Triggers
- When agent needs cross-asset correlation
- When user requests correlation matrix, diversification, or hedging pairs
- When assessing regime (risk-on/risk-off) from correlations
- When building pairs or sector rotation signals

## Inputs
- `symbols`: string[] — Assets: SPY, QQQ, XLF, USD/JPY, etc.
- `returns`: object — Symbol -> array of returns (optional; else fetch prices)
- `lookback_days`: number — Days for correlation (default: 20)
- `frequency`: string — "daily", "hourly" (default: daily)
- `min_periods`: number — Min observations (default: 10)

## Outputs
- `correlation_matrix`: object — Symbol pair -> correlation (-1 to 1)
- `avg_correlation`: number — Average pairwise correlation (regime indicator)
- `divergence_pairs`: object[] — Pairs with unusual correlation change
- `regime_signal`: string — "risk_on", "risk_off", "mixed" (from correlation structure)
- `metadata`: object — Symbols, lookback, computed_at

## Steps
1. Fetch or use returns for each symbol over lookback
2. Compute pairwise correlation (Pearson)
3. Build correlation matrix
4. Avg correlation: high = risk-on (everything moves together), low = risk-off
5. Compare to rolling prior period for divergence_pairs
6. Derive regime_signal from avg and sector correlations
7. Return matrix, avg, divergence_pairs, regime_signal
8. Cache with 1h TTL for daily; 15m for hourly

## Example
```
Input: symbols=["SPY","QQQ","XLF","USDJPY"], lookback_days=20
Output: {
  correlation_matrix: {SPY_QQQ: 0.95, SPY_XLF: 0.88, SPY_USDJPY: -0.45},
  avg_correlation: 0.72,
  divergence_pairs: [{pair:"SPY_QQQ", current:0.95, prior:0.92, change:0.03}],
  regime_signal: "risk_on",
  metadata: {symbols:["SPY","QQQ","XLF","USDJPY"], lookback:20, computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- High avg correlation = diversification harder; consider hedges
- USD/JPY often inverse to risk assets
- Sector leaders (XLK, XLF) for sector rotation
