# ETF Inflow Tracker

## Purpose
Track where passive money flows in ETFs to predict sector moves and rotation.

## Category
strategy

## Triggers
- On daily ETF flow data update (e.g., from ETF.com, Bloomberg)
- When user requests sector flow analysis
- When building sector-rotation or thematic signals
- Before market open to anticipate opening pressure

## Inputs
- `etf_universe`: string[] — ETFs to track (default: SPY, QQQ, sector SPDRs, thematic)
- `flow_data`: object — Source: {symbol: {flow_usd, aum, flow_pct}}
- `lookback_days`: number — Days of flow history (default: 5)
- `sector_mapping`: object — ETF -> sector (e.g., XLF -> Financials)

## Outputs
- `flow_signals`: object[] — [{etf, flow_usd, flow_pct, sector, signal}]
- `sector_rank`: object[] — Sectors ranked by net flow (strongest first)
- `rotation_signal`: string — "INTO_GROWTH" | "INTO_VALUE" | "INTO_DEFENSIVE" | "NEUTRAL"
- `top_inflows`: string[] — ETF symbols with largest inflows
- `top_outflows`: string[] — ETF symbols with largest outflows
- `metadata`: object — as_of_date, n_etfs

## Steps
1. Load flow_data for etf_universe over lookback_days
2. Aggregate by sector using sector_mapping
3. Compute flow_pct = flow_usd / aum for each ETF
4. Rank sectors by net flow; identify rotation (e.g., XLF up, XLU down = into financials)
5. Set rotation_signal from sector rank shifts
6. Return flow_signals, sector_rank, rotation_signal, top_inflows, top_outflows, metadata
7. Use with sector-rotation or sector-rotation-intraday for execution

## Example
```
Input: etf_universe=["SPY","QQQ","XLF","XLK","XLE"], flow_data={...}, lookback_days=5
Output: {
  flow_signals: [{etf: "XLF", flow_usd: 1.2e9, flow_pct: 2.1, sector: "Financials", signal: "BULLISH"}],
  sector_rank: [{sector: "Financials", net_flow: 1.2e9}, {sector: "Tech", net_flow: 0.8e9}],
  rotation_signal: "INTO_VALUE",
  top_inflows: ["XLF", "XLE"],
  top_outflows: ["XLU"],
  metadata: {as_of_date: "2025-03-03", n_etfs: 15}
}
```

## Notes
- Flow data often T+1; use prior day for pre-market
- Thematic ETFs (ARKK, etc.) can lead sector moves
- Correlate with etf-holdings-fetch for underlying exposure
