# Institutional Holdings

## Purpose
Fetch 13F institutional holding data to track hedge fund and asset manager positions for flow and sentiment signals.

## Category
data

## Triggers
- When agent needs institutional ownership or 13F data
- When user requests hedge fund holdings, smart money flow, or 13F filings
- When building conviction from institutional accumulation
- When validating whale activity or sector rotation by institutions

## Inputs
- `symbol`: string — Ticker to look up (string)
- `institution`: string — Specific institution name or CIK (string, optional)
- `filing_type`: string — "13F", "13F-HR", "13F-HR/A" (string, default: "13F")
- `quarter`: string — Quarter, e.g. "2024Q4" (string, optional)
- `top_holders`: number — Number of top holders to return (number, optional)
- `provider`: string — "sec", "quiver", "whale_wisdom", or default (string)

## Outputs
- `holdings`: object[] — Institution, shares, value, change vs prior (object[])
- `top_buyers`: object[] — Institutions that increased position (object[])
- `top_sellers`: object[] — Institutions that decreased position (object[])
- `aggregate_change`: object — Net institutional change (object)
- `metadata`: object — Filing date, quarter, data source (object)

## Steps
1. Resolve 13F data provider (SEC EDGAR, Quiver, WhaleWisdom)
2. If symbol: fetch all 13F filings that report the symbol
3. If institution: fetch that institution's 13F for quarter
4. Parse holdings: institution name, shares, market value, option type
5. Compare to prior quarter for change (new, added, reduced, sold)
6. Rank by position size or by change magnitude
7. Aggregate: total shares held by institutions, net change
8. Return top_holders if specified
9. Cache by quarter; 13F filings have 45-day lag
10. Return structured output with metadata

## Example
```
Input: symbol="NVDA", quarter="2024Q4", top_holders=5
Output: {
  holdings: [{institution: "Berkshire Hathaway", shares: 1500000, value: 1.2e9, change: "added"}],
  top_buyers: [{institution: "Tiger Global", shares_added: 500000}],
  top_sellers: [{institution: "Citadel", shares_sold: 200000}],
  aggregate_change: {net_shares: 2000000, direction: "accumulation"},
  metadata: {quarter: "2024Q4", filing_deadline: "2025-02-14"}
}
```

## Notes
- 13F data is quarterly and 45 days delayed
- Options reported separately; some institutions use swaps (not in 13F)
- Large institutions may split across multiple filings
