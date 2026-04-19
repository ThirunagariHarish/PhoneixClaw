# Option Sweep Detector

## Purpose
Detect aggressive options "sweep" orders across exchanges indicating institutional or smart money flow.

## Category
analysis

## Triggers
- When user requests sweep detection for a symbol
- When building options flow signals from aggressive buying/selling
- When screening for unusual institutional activity
- When assessing bullish/bearish options sentiment from sweeps

## Inputs
- `symbol`: string — Underlying ticker (e.g., AAPL, SPY)
- `sweep_data`: object[] — Pre-fetched options flow (or fetch from unusual-whales-flow, CBOE)
- `min_premium`: number — Min premium per sweep in USD (default: 50000)
- `lookback_minutes`: number — Window for sweep aggregation (default: 60)
- `exchange_filter`: string[] — Exchanges to include (default: all)
- `include_oi_change`: boolean — Require OI increase (default: true)

## Outputs
- `sweeps`: object[] — [{strike, expiry, type, premium, direction, exchange, timestamp}]
- `bullish_premium`: number — Total premium of bullish sweeps (calls bought, puts sold)
- `bearish_premium`: number — Total premium of bearish sweeps (puts bought, calls sold)
- `net_sentiment`: string — "bullish", "bearish", "neutral"
- `sweep_count`: number — Count of sweeps in window
- `metadata`: object — symbol, lookback, computed_at

## Steps
1. Fetch options flow or accept sweep_data; filter by symbol, lookback_minutes
2. Identify sweeps: same strike/expiry/type bought across multiple exchanges in short window
3. Filter by min_premium; optionally require OI increase (new positions)
4. Classify: call buy = bullish, put buy = bearish; call sell = bearish, put sell = bullish
5. Aggregate bullish_premium and bearish_premium
6. net_sentiment: bullish_premium > bearish_premium = bullish, else bearish or neutral
7. Return sweeps, bullish_premium, bearish_premium, net_sentiment, sweep_count, metadata
8. Cache with 5m TTL

## Example
```
Input: symbol="NVDA", min_premium=50000, lookback_minutes=60
Output: {
  sweeps: [
    {strike: 900, expiry: "2025-03-21", type: "call", premium: 75000, direction: "bullish", exchange: "CBOE", timestamp: "2025-03-03T14:45:00Z"}
  ],
  bullish_premium: 125000,
  bearish_premium: 40000,
  net_sentiment: "bullish",
  sweep_count: 3,
  metadata: {symbol: "NVDA", lookback: 60, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Requires options flow data; use unusual-whales-flow, CBOE, or similar
- Sweeps indicate urgency; combine with options-flow-scanner for full flow view
- False positives from retail; min_premium helps filter
