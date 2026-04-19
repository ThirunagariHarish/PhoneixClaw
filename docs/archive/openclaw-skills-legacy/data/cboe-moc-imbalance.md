# CBOE Market-on-Close Imbalance

## Purpose
Fetch CBOE MOC (Market-on-Close) imbalance data from the 3:50 PM ET feed for end-of-day trading and imbalance signals.

## Category
data

## API Integration
- Provider: CBOE; Data feed (vendor-dependent; e.g., Polygon, DTN, direct); Auth varies by vendor; Real-time 3:50 PM ET; Cost tier varies

## Triggers
- When agent needs MOC imbalance for EOD trading
- When user requests imbalance, MOC, or 3:50 PM data
- When building imbalance-based entry/exit signals
- When assessing buy/sell pressure at market close

## Inputs
- `symbols`: string[] — Tickers to fetch (optional; empty = all available)
- `as_of`: string — ISO date (default: today)
- `include_historical`: boolean — Fetch prior days (optional)
- `min_imbalance_pct`: number — Filter by imbalance % (optional)

## Outputs
- `imbalances`: object[] — Per symbol: symbol, buy_imbalance, sell_imbalance, net, imbalance_ratio
- `aggregate`: object — Total buy/sell imbalance across symbols
- `metadata`: object — Source, as_of, published_at (3:50 PM ET)

## Steps
1. Connect to CBOE MOC feed via configured vendor (Polygon, DTN, etc.)
2. MOC data published ~3:50 PM ET; fetch at or after that time
3. Parse imbalance: buy MOC shares, sell MOC shares, net
4. Compute imbalance_ratio = (buy - sell) / (buy + sell) or similar
5. Filter by symbols if provided
6. Filter by min_imbalance_pct if specified
7. Aggregate total buy/sell across universe
8. Return imbalances array and metadata
9. Cache until next trading day; data is daily

## Example
```
Input: symbols=["AAPL","NVDA","SPY"], as_of="2025-03-03"
Output: {
  imbalances: [
    {symbol:"AAPL",buy_imbalance:125000,sell_imbalance:98000,net:27000,imbalance_ratio:0.12},
    {symbol:"NVDA",buy_imbalance:85000,sell_imbalance:120000,net:-35000,imbalance_ratio:-0.17}
  ],
  aggregate: {buy:210000,sell:218000,net:-8000},
  metadata: {source:"cboe", as_of:"2025-03-03", published_at:"2025-03-03T20:50:00Z"}
}
```

## Notes
- MOC feed typically requires data subscription (CBOE, vendor)
- 3:50 PM ET is approximate; check vendor docs
- Large imbalances can move price in final minutes
