# Cross-Asset Correlation Matrix

## Purpose
Compute cross-asset correlation matrix for a set of symbols to assess diversification, hedge effectiveness, and regime-dependent relationships.

## Category
analysis

## Triggers
- When the agent needs correlation structure for a portfolio
- When user requests correlation matrix or cross-asset relationships
- When building diversified portfolios or hedging
- When evaluating regime changes in asset relationships

## Inputs
- `symbols`: string[] — List of tickers (e.g., ["SPY", "QQQ", "AAPL", "TLT", "GLD"])
- `lookback_days`: number — Days for return correlation (default: 60)
- `timeframe`: string — "1d" for daily returns (default)
- `method`: string — "pearson", "spearman" (default: pearson)
- `returns_data`: object — Optional pre-fetched returns; if empty, fetch via market-data-fetcher

## Outputs
- `correlation_matrix`: object — NxN matrix of pairwise correlations
- `eigenvalues`: number[] — Eigenvalues of correlation matrix (for dimensionality)
- `clusters`: object[] — Groups of highly correlated assets (if clustering requested)
- `avg_correlation`: number — Mean off-diagonal correlation
- `metadata`: object — Symbols, lookback_days, method, computed_at

## Steps
1. Fetch OHLCV for all symbols if not provided
2. Compute log returns for each symbol over lookback_days
3. Build returns matrix: rows = days, columns = symbols
4. Compute pairwise correlation matrix using method (pearson or spearman)
5. Optionally compute eigenvalues for correlation matrix (PCA dimensionality)
6. Optionally cluster assets by correlation (e.g., hierarchical clustering)
7. Compute avg_correlation: mean of upper triangle (excluding diagonal)
8. Return correlation_matrix, eigenvalues, clusters, avg_correlation
9. Flag high-correlation pairs (>0.8) for diversification warning
10. Return metadata with symbols, lookback, method, computed_at

## Example
```
Input: symbols=["SPY", "QQQ", "TLT", "GLD"], lookback_days=60, method="pearson"
Output: {
  correlation_matrix: {
    SPY: {SPY: 1, QQQ: 0.95, TLT: -0.3, GLD: 0.1},
    QQQ: {SPY: 0.95, QQQ: 1, TLT: -0.25, GLD: 0.05},
    ...
  },
  avg_correlation: 0.2,
  eigenvalues: [2.1, 0.9, 0.6, 0.4],
  metadata: {symbols: ["SPY","QQQ","TLT","GLD"], lookback_days: 60, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Correlations are regime-dependent; crisis periods often show correlation breakdown
- Use rolling windows to detect regime shifts
- High correlation reduces diversification benefit; consider alternative assets
