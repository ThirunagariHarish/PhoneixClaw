# Skill: Options Flow Scanner

## Purpose
Scan and ingest unusual options activity from Unusual Whales or similar data providers to identify large, non-standard options trades that may signal institutional positioning.

## Triggers
- When the agent needs to monitor unusual options flow for trading signals
- When user requests options flow data or unusual activity alerts
- When building options-based signal pipelines
- When analyzing institutional positioning before earnings or catalysts

## Inputs
- `symbol`: string — Optional ticker to filter (empty = all symbols)
- `min_premium`: number — Minimum premium in USD to consider "unusual" (default: 100000)
- `lookback_minutes`: number — Minutes of flow to fetch (default: 60)
- `flow_type`: string — "calls", "puts", "sweeps", "blocks", or "all"
- `data_source`: string — "unusual_whales", "flowalgo", or configured provider

## Outputs
- `flows`: object[] — Flow records: symbol, expiry, strike, type, premium, sentiment, timestamp
- `aggregated_sentiment`: object — Per-symbol bullish/bearish score
- `metadata`: object — Scan time, flow_count, data_source

## Steps
1. Connect to configured options flow provider API (Unusual Whales, FlowAlgo, etc.)
2. Build query with symbol filter, time range, and min_premium threshold
3. Fetch raw flow data; handle pagination if provider limits results per request
4. Parse each flow: symbol, underlying_expiry, strike, option_type (call/put), premium, open_interest_change
5. Classify flow type: sweep (multi-leg), block (large single), or single
6. Compute sentiment per flow: bullish (call buy, put sell) vs bearish (put buy, call sell)
7. Filter by flow_type if specified (calls-only, puts-only, sweeps, blocks)
8. Sort by premium descending to prioritize largest trades
9. Aggregate sentiment per symbol: sum premium-weighted bullish vs bearish
10. Return flows array with aggregated sentiment and metadata

## Example
```
Input: symbol="NVDA", min_premium=250000, lookback_minutes=120, flow_type="sweeps"
Output: {
  flows: [{symbol: "NVDA", strike: 950, type: "call", premium: 450000, sentiment: "bullish", timestamp: "2025-03-03T14:45:00Z"}],
  aggregated_sentiment: {NVDA: {bullish_score: 0.72, bearish_score: 0.28, net_premium: 1200000}},
  metadata: {scanned_at: "2025-03-03T15:00:00Z", flow_count: 23, data_source: "unusual_whales"}
}
```
