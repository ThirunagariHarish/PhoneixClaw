# ETF Holdings Fetch

## Purpose
Fetch ETF constituent holdings, weights, and rebalancing data for sector exposure and replication analysis.

## Category
data

## Triggers
- When agent needs ETF composition for exposure or replication
- When user requests ETF holdings, sector weights, or top constituents
- When building sector/thematic exposure from ETF holdings
- When validating overlap between ETFs or building custom baskets

## Inputs
- `etf_symbols`: string[] — ETF tickers, e.g. ["SPY","QQQ","XLK"] (string[])
- `data_type`: string — "holdings", "weights", "sectors", "top_n" (string)
- `top_n`: number — Number of top holdings to return (number, optional)
- `as_of_date`: string — Holdings as-of date (string, optional)
- `provider`: string — "etfdb", "factset", "polygon", or default (string)

## Outputs
- `holdings`: object[] — Constituent ticker, shares, weight per ETF (object[])
- `weights`: object — Top holdings with weight % per ETF (object)
- `sectors`: object — Sector allocation % per ETF (object)
- `metadata`: object — As-of date, provider, ETF count (object)

## Steps
1. Resolve ETF holdings provider from input or config
2. Fetch holdings file or API for each ETF symbol
3. For holdings: return full list with ticker, shares, market value, weight
4. For weights: return top N by weight, sorted descending
5. For sectors: aggregate by sector (GICS or provider classification)
6. Normalize weight to sum to 100% per ETF
7. Handle as_of_date: use latest if not specified
8. Cache holdings; they typically update daily or at rebalance
9. Return structured output with metadata
10. Support overlap analysis: common holdings across ETFs if multiple requested

## Example
```
Input: etf_symbols=["SPY","QQQ"], data_type="top_n", top_n=10
Output: {
  weights: {
    SPY: [{ticker: "AAPL", weight: 7.2}, {ticker: "MSFT", weight: 6.8}],
    QQQ: [{ticker: "AAPL", weight: 8.5}, {ticker: "MSFT", weight: 8.1}]
  },
  metadata: {as_of: "2025-03-01", provider: "etfdb"}
}
```

## Notes
- Holdings can lag by 1-2 days; check as-of date
- Some ETFs use sampling; full replication not always available
- Sector classification may vary by provider
