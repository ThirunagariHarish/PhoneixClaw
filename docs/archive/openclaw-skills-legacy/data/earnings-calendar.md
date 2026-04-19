# Skill: Earnings Calendar

## Purpose
Fetch upcoming earnings dates, estimates (EPS, revenue), and historical actuals to avoid holding through earnings or to trade earnings catalysts.

## Triggers
- When the agent needs earnings dates for position management
- When user requests earnings calendar or upcoming earnings
- When filtering trades around earnings (avoid or target)
- When building earnings-based strategy pipelines

## Inputs
- `symbols`: string[] — Tickers to fetch (empty = broad calendar)
- `horizon_days`: number — Days ahead to include (default: 14)
- `include_estimates`: boolean — Fetch EPS/revenue estimates (default: true)
- `include_historical`: boolean — Include recent actuals for context (default: false)

## Outputs
- `earnings`: object[] — Symbol, date, time (BMO/AMC), eps_estimate, revenue_estimate, actual (if historical)
- `warnings`: string[] — Symbols with earnings in next N days for risk
- `metadata`: object — Fetch time, symbol count

## Steps
1. Connect to earnings data provider (Alpha Vantage, Polygon, Yahoo, or internal DB)
2. For each symbol, fetch upcoming earnings within horizon_days
3. Parse earnings date, time (before/after market), fiscal quarter
4. If include_estimates: fetch consensus EPS and revenue estimates
5. If include_historical: fetch last quarter actuals for beat/miss context
6. Normalize date format (YYYY-MM-DD) and timezone (market hours)
7. Sort by date ascending; flag earnings within 1-2 days as "imminent"
8. Build warnings array for symbols with earnings in next 3 days
9. Handle symbols with no upcoming earnings (return empty or TBD)
10. Return earnings array with metadata

## Example
```
Input: symbols=["NVDA", "AAPL"], horizon_days=14, include_estimates=true
Output: {
  earnings: [{symbol: "NVDA", date: "2025-03-05", time: "AMC", eps_estimate: 5.82, revenue_estimate: 28.5e9}],
  warnings: ["NVDA has earnings in 2 days - consider reducing exposure"],
  metadata: {fetched_at: "2025-03-03T15:00:00Z", symbols: 2}
}
```
