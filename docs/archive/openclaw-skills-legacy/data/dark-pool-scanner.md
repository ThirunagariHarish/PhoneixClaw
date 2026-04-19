# Skill: Dark Pool Scanner

## Purpose
Scan dark pool transactions to identify large block trades that may indicate institutional accumulation or distribution, often ahead of price moves.

## Triggers
- When the agent needs dark pool flow data for a symbol
- When user requests dark pool scanning or block trade monitoring
- When building institutional flow signal pipelines
- When assessing accumulation/distribution alongside options flow

## Inputs
- `symbol`: string — Ticker to scan (required)
- `min_size`: number — Minimum share size to consider (default: 10000)
- `lookback_hours`: number — Hours of dark pool prints (default: 24)
- `aggregation`: string — "net_volume", "print_count", or "both"

## Outputs
- `prints`: object[] — Individual prints: symbol, size, price, timestamp, venue
- `aggregated`: object — Net buy/sell volume, print count, avg size
- `signal`: string — "accumulation", "distribution", or "neutral"
- `metadata`: object — Scan time, print_count

## Steps
1. Connect to dark pool data provider (Unusual Whales, Quiver, or exchange-reported data)
2. Query dark pool prints for symbol within lookback_hours
3. Filter by min_size to focus on institutional-sized blocks
4. Parse each print: symbol, shares, price, timestamp, dark pool venue (if available)
5. Classify prints as buy or sell (use tape: print above bid = buy, below ask = sell, or provider classification)
6. Aggregate: sum buy volume, sum sell volume, count of prints
7. Compute net_volume = buy_volume - sell_volume; net positive suggests accumulation
8. Derive signal: accumulation (net > threshold), distribution (net < -threshold), neutral
9. Sort prints by timestamp descending for recency
10. Return prints, aggregated stats, signal, and metadata

## Example
```
Input: symbol="NVDA", min_size=25000, lookback_hours=12
Output: {
  prints: [{symbol: "NVDA", size: 50000, price: 875.20, timestamp: "2025-03-03T14:30:00Z"}],
  aggregated: {buy_volume: 450000, sell_volume: 120000, net_volume: 330000, print_count: 18},
  signal: "accumulation",
  metadata: {scanned_at: "2025-03-03T15:00:00Z", print_count: 18}
}
```
