# Systemic Risk Heatmap

## Purpose
Map sectors and names vulnerable to contagion and systemic risk for position sizing and hedging.

## Category
strategy

## Triggers
- When VIX spikes or stress indicators rise
- On user request for risk heatmap
- Before increasing exposure in correlated names
- When building portfolio stress-test or VaR

## Inputs
- `sectors`: string[] — Sectors to analyze (default: GICS sectors)
- `correlation_matrix`: object — Pairwise correlation of returns
- `liquidity_metrics`: object — Per-name bid-ask, volume, depth
- `stress_indicators`: object — {vix, credit_spread, funding_rate}
- `position_holdings`: object[] — Optional; current positions for exposure calc

## Outputs
- `heatmap`: object — {sector: risk_score 0-100} per sector
- `vulnerable_names`: string[] — Names with high correlation + low liquidity
- `contagion_paths`: object[] — [{from, to, correlation, risk}]
- `hedge_suggestions`: string[] — Instruments to reduce systemic exposure
- `overall_risk_score`: number — 0-100 portfolio-level systemic risk
- `metadata`: object — vix_level, as_of_timestamp

## Steps
1. Load correlation_matrix; identify high-correlation clusters
2. Overlay liquidity_metrics; flag low-liquidity names in clusters
3. Score each sector: correlation density + liquidity + stress_indicators
4. Build contagion_paths: if sector A fails, which sectors/names cascade
5. Compute overall_risk_score from position_holdings and heatmap
6. Suggest hedges: VIX calls, sector shorts, or uncorrelated assets
7. Return heatmap, vulnerable_names, contagion_paths, hedge_suggestions, overall_risk_score, metadata
8. Use with correlation-risk-monitor or stress-test-runner

## Example
```
Input: sectors=["Financials","Tech","Energy"], correlation_matrix={...}, stress_indicators={vix: 22}
Output: {
  heatmap: {Financials: 72, Tech: 55, Energy: 48},
  vulnerable_names: ["Regional Bank ETF", "Small Cap Tech"],
  contagion_paths: [{from: "Financials", to: "Real Estate", correlation: 0.78, risk: "high"}],
  hedge_suggestions: ["VIXY calls", "Reduce financials exposure"],
  overall_risk_score: 61,
  metadata: {vix_level: 22, as_of_timestamp: "2025-03-03T14:00:00Z"}
}
```

## Notes
- Correlations rise in stress; use stressed correlation if available
- Integrate with correlation-guard for entry blocking
- Update heatmap intraday during volatile sessions
