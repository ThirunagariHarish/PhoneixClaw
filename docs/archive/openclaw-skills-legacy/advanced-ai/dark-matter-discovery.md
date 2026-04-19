# Dark Matter Discovery

## Purpose
ML discovery of non-obvious cross-asset correlations and latent factors that drive returns.

## Category
advanced-ai

## Triggers
- When user requests "hidden" or "non-obvious" correlation discovery
- When building factor models or diversification analysis
- Periodically for regime discovery (e.g., weekly)
- When correlation-risk-monitor needs enhanced inputs

## Inputs
- `asset_returns`: object — {symbol: [returns]} or fetch from market data
- `asset_universe`: string[] — Symbols to analyze (default: SPY, sectors, bonds, commodities)
- `lookback_days`: number — Days for correlation/factor (default: 252)
- `method`: string — "pca", "ica", "cca", "auto" (default: auto)
- `n_factors`: number — Number of latent factors to extract (default: 5)

## Outputs
- `latent_factors`: object[] — [{name, loadings, variance_explained}]
- `asset_factor_loadings`: object — {symbol: {factor_1: load, ...}}
- `discovered_correlations`: object[] — [{asset_a, asset_b, correlation, lag}]
- `surprise_pairs`: object[] — Pairs with unexpected correlation (vs historical)
- `metadata`: object — method, lookback, n_factors, computed_at

## Steps
1. Fetch or receive asset_returns for asset_universe
2. Apply method: PCA for linear factors, ICA for independent, CCA for cross-asset
3. Extract n_factors; compute loadings per asset
4. discovered_correlations: residual correlations after factor removal; or lagged correlations
5. surprise_pairs: correlations that changed significantly vs rolling lookback
6. Return latent_factors, asset_factor_loadings, discovered_correlations, surprise_pairs, metadata
7. Use for diversification, risk decomposition, regime detection

## Example
```
Input: asset_universe=["SPY","TLT","GLD","DXY","VIX"], lookback_days=252, method="pca", n_factors=5
Output: {
  latent_factors: ["risk_on_off", "rates", "dollar", "commodity", "vol"],
  asset_factor_loadings: {SPY: {risk_on_off: 0.9, rates: -0.2, ...}, ...},
  discovered_correlations: [{asset_a: "TLT", asset_b: "SPY", correlation: -0.6, lag: 0}],
  surprise_pairs: [{asset_a: "GLD", asset_b: "DXY", correlation: -0.4, change: 0.3}],
  metadata: {method: "pca", lookback: 252, n_factors: 5, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Requires model-trainer-pytorch or similar for PCA/ICA/CCA
- "Dark matter" = non-obvious correlations not in standard factor models
- Integrate with correlation-risk-monitor and correlation-guard for risk decomposition
