# Polygon.io Snapshot & Aggregates

## Purpose
Fetch real-time snapshot (quote, trade, minute bar) and aggregates from Polygon.io for live market data.

## Category
data

## API Integration
- Provider: Polygon.io; REST API; API key in query param or header; 5 req/min (free tier); Free tier available

## Triggers
- When agent needs real-time snapshot or aggregates
- When user requests live quote, last trade, or minute bars
- When building intraday signals from Polygon
- When free tier is sufficient for low-frequency checks

## Inputs
- `symbols`: string[] — Tickers (e.g., AAPL, SPY)
- `data_type`: string — "snapshot", "quote", "trade", "minute_aggs"
- `multiplier`: number — Bar size for aggs: 1, 5, 15 (optional)
- `timespan`: string — "minute", "hour", "day" (optional)
- `from`: string — ISO datetime for aggs (optional)
- `to`: string — ISO datetime for aggs (optional)

## Outputs
- `snapshot`: object — Per symbol: bid, ask, last, volume, vwap, open, high, low
- `aggregates`: object[] — OHLCV bars if requested
- `metadata`: object — Source, fetched_at, rate_limit_remaining

## Steps
1. For snapshot: call /v2/snapshot/locale/us/markets/stocks/tickers
2. For aggregates: call /v2/aggs/ticker/{ticker}/range
3. Add API key in Authorization header or query
4. Respect 5 req/min; batch symbol requests when possible
5. Parse snapshot: bid, ask, last, volume, prev close, day open/high/low
6. Parse aggregates: o, h, l, c, v, vw, t (timestamp)
7. Return snapshot and/or aggregates
8. Cache snapshot 30s; aggregates 1m

## Example
```
Input: symbols=["AAPL","NVDA"], data_type="snapshot"
Output: {
  snapshot: {
    AAPL: {bid:175.48,ask:175.52,last:175.50,volume:52000000,vwap:175.35,open:175.20,high:175.65,low:175.10},
    NVDA: {bid:895.20,ask:895.50,last:895.35,volume:28000000,vwap:894.80}
  },
  metadata: {source:"polygon", fetched_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- Free tier: 5 req/min; upgrade for higher throughput
- Snapshot includes day bar; aggregates for historical minute bars
- Use batch endpoint for multiple symbols to conserve rate limit
