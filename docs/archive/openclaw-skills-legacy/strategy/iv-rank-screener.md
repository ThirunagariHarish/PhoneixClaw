# Skill: IV Rank Screener

## Purpose
Screen options underlyings by implied volatility rank (IV rank) to find elevated-volatility names for premium selling or depressed-volatility names for long-volatility plays.

## Triggers
- When the agent needs IV rank for options strategies
- When user requests high-IV or low-IV underlyings
- When building options watchlists by volatility
- When validating premium-selling or long-vol entry timing

## Inputs
- `symbols`: string[] — Underlyings to screen
- `direction`: string — "high", "low", or "all" — filter by IV rank
- `min_iv_rank`: number — Minimum IV rank for "high" filter (default: 50)
- `max_iv_rank`: number — Maximum IV rank for "low" filter (default: 25)
- `provider`: string — Options data provider (e.g., "polygon", "tradier")

## Outputs
- `ranked`: object[] — Symbols with IV rank, IV, and metadata
- `high_iv`: object[] — Symbols meeting high IV rank criteria
- `low_iv`: object[] — Symbols meeting low IV rank criteria
- `metadata`: object — Provider, scan time, symbol count

## Steps
1. Fetch options chain or IV surface for symbols via options-flow-scanner or provider API
2. Extract ATM implied volatility for each symbol
3. Fetch or use cached historical IV (e.g., 52-week high/low)
4. IV rank = (current_IV - 52w_low) / (52w_high - 52w_low) * 100
5. Rank symbols by IV rank (descending for high, ascending for low)
6. Filter by direction: high (rank >= min_iv_rank), low (rank <= max_iv_rank)
7. Return ranked list, high_iv, low_iv subsets
8. Cache IV data with daily TTL

## Example
```
Input: symbols=["NVDA","AAPL","TSLA"], direction="high", min_iv_rank=50
Output: {
  ranked: [{symbol: "TSLA", iv_rank: 72, iv: 0.45}, {symbol: "NVDA", iv_rank: 58, iv: 0.38}],
  high_iv: [{symbol: "TSLA", iv_rank: 72}, {symbol: "NVDA", iv_rank: 58}],
  low_iv: [],
  metadata: {provider: "polygon", scanned_at: "2025-03-03T15:00:00Z"}
}
```
