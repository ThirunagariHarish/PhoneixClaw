# Correlation Risk Monitor

## Purpose
Monitor portfolio correlation risk to detect crowded trades and over-concentration in correlated assets.

## Category
risk

## Triggers
- Before adding new positions
- When portfolio composition changes
- When user requests correlation analysis or crowded-trade check
- Periodically (e.g., hourly) for live risk dashboard

## Inputs
- `positions`: object[] — Current positions: {symbol, value, weight_pct}
- `correlation_matrix`: object — Symbol-pair correlations (or fetch from cross-asset-correlation)
- `lookback_days`: number — Days for correlation calc (default: 60)
- `cluster_threshold`: number — Correlation above this = same cluster (default: 0.7)
- `max_cluster_weight_pct`: number — Max portfolio weight in one cluster (default: 40)
- `sector_mapping`: object — Optional: symbol -> sector for sector concentration

## Outputs
- `cluster_weights`: object — Cluster ID -> weight_pct
- `crowded_trades`: string[] — Symbols in over-weighted clusters
- `correlation_risk_score`: number — 0–100 composite risk score
- `recommendations`: string[] — Suggested actions (e.g., "Reduce tech cluster")
- `metadata`: object — Clusters, matrix_summary, thresholds

## Steps
1. Fetch or compute correlation_matrix for position symbols
2. Cluster symbols: correlation >= cluster_threshold -> same cluster
3. Sum position weights per cluster
4. Identify clusters where weight > max_cluster_weight_pct
5. crowded_trades = symbols in over-weighted clusters
6. Compute correlation_risk_score: weighted by cluster concentration and correlation strength
7. Generate recommendations: reduce size in crowded clusters, diversify
8. Return cluster_weights, crowded_trades, correlation_risk_score, recommendations, metadata
9. Emit alert if correlation_risk_score > threshold (e.g., 70)
10. Integrate with position-exposure-checker for combined risk view

## Example
```
Input: positions=[{symbol: "AAPL", weight_pct: 15}, {symbol: "MSFT", weight_pct: 12}, {symbol: "NVDA", weight_pct: 18}],
       cluster_threshold=0.7, max_cluster_weight_pct=40
Output: {
  cluster_weights: {"tech_mega": 45},
  crowded_trades: ["AAPL", "MSFT", "NVDA"],
  correlation_risk_score: 72,
  recommendations: ["Reduce tech mega-cap cluster; consider diversifying into uncorrelated assets"],
  metadata: {clusters: 1, max_cluster: "tech_mega"}
}
```

## Notes
- Correlation matrix can be from historical returns or factor model
- Sector mapping improves cluster detection when correlation data is sparse
- Correlations can spike in stress; consider stressed correlation scenarios
