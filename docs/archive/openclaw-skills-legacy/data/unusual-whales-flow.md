# Unusual Whales Options Flow

## Purpose
Fetch real-time and historical unusual options flow alerts from Unusual Whales API for flow-based trading signals.

## Category
data

## API Integration
- Provider: Unusual Whales; REST API; API key in `Authorization: Bearer <token>`; 120 req/min; $49/mo tier

## Triggers
- When agent needs unusual options flow or sweeps
- When user requests flow alerts, sweeps, or block options activity
- When building flow-based entry/exit signals
- When screening for high-conviction institutional options activity

## Inputs
- `symbols`: string[] — Tickers to filter (optional; empty = all)
- `flow_type`: string — "sweep", "block", "unusual", "split" (optional)
- `min_premium`: number — Min premium in USD (optional)
- `start`: string — ISO datetime for historical (optional)
- `end`: string — ISO datetime for historical (optional)
- `limit`: number — Max results (default: 50)

## Outputs
- `flows`: object[] — Flow records: symbol, expiry, strike, type, premium, sentiment, timestamp
- `aggregate`: object — Total premium, count by type
- `metadata`: object — Source, fetched_at, rate_limit_remaining

## Steps
1. Build request to Unusual Whales flow endpoint with filters
2. Add `Authorization: Bearer <API_KEY>` header
3. Respect 120 req/min; use exponential backoff on 429
4. Parse response: symbol, expiry, strike, call/put, premium, sentiment
5. Filter by min_premium and symbols if provided
6. Sort by timestamp descending
7. Aggregate total premium and flow counts
8. Return flows array and metadata
9. Cache with 60s TTL for real-time; longer for historical

## Example
```
Input: symbols=["NVDA","TSLA"], flow_type="sweep", min_premium=100000
Output: {
  flows: [{symbol:"NVDA",expiry:"2025-03-21",strike:900,type:"call",premium:125000,sentiment:"bullish",timestamp:"2025-03-03T14:32:00Z"}],
  aggregate: {total_premium: 450000, sweep_count: 3},
  metadata: {source:"unusual-whales", fetched_at:"2025-03-03T14:35:00Z"}
}
```

## Notes
- 120 req/min limit; batch requests when possible
- Premium in USD; sentiment is provider-derived
- Historical data availability depends on subscription tier
