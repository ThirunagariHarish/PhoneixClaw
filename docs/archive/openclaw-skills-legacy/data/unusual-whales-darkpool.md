# Unusual Whales Dark Pool

## Purpose
Fetch dark pool prints, levels, and block activity from Unusual Whales for institutional flow and liquidity analysis.

## Category
data

## API Integration
- Provider: Unusual Whales; REST API; API key in `Authorization: Bearer <token>`; 120 req/min; $49/mo tier

## Triggers
- When agent needs dark pool prints or block levels
- When user requests dark pool activity, block prints, or off-exchange flow
- When assessing institutional accumulation/distribution
- When building liquidity heat maps from dark pool data

## Inputs
- `symbols`: string[] — Tickers to filter (optional)
- `min_size`: number — Min shares per print (optional, default: 10000)
- `start`: string — ISO date for historical (optional)
- `end`: string — ISO date for historical (optional)
- `include_levels`: boolean — Include price level aggregates (default: true)

## Outputs
- `prints`: object[] — Dark pool prints: symbol, price, size, time, venue
- `levels`: object — Price level aggregates (price -> total volume)
- `aggregate`: object — Total dark volume, print count per symbol
- `metadata`: object — Source, date range, fetched_at

## Steps
1. Call Unusual Whales dark pool endpoint with symbol/time filters
2. Add API key in Authorization header
3. Respect 120 req/min rate limit
4. Parse prints: symbol, price, size, timestamp, venue
5. Filter by min_size if provided
6. Aggregate by price level when include_levels=true
7. Compute total volume and print count per symbol
8. Return prints, levels, aggregate, metadata
9. Cache with 5m TTL for intraday

## Example
```
Input: symbols=["AAPL","NVDA"], min_size=50000, include_levels=true
Output: {
  prints: [{symbol:"AAPL",price:175.50,size:75000,timestamp:"2025-03-03T14:22:00Z",venue:"dark"}],
  levels: {175.50: 75000, 175.25: 52000},
  aggregate: {AAPL: {volume: 127000, count: 2}, NVDA: {volume: 89000, count: 1}},
  metadata: {source:"unusual-whales", fetched_at:"2025-03-03T14:25:00Z"}
}
```

## Notes
- Dark pool prints may be delayed; check provider SLA
- Levels useful for support/resistance from institutional flow
- 120 req/min shared with flow API on same tier
