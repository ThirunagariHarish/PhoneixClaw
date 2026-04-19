# Iceberg Order Detector

## Purpose
Identify hidden institutional iceberg orders from tape analysis (volume patterns, fill sequences, order book imbalance).

## Category
execution

## Triggers
- When analyzing order flow for large institutional presence
- When user requests iceberg detection or "hidden order" analysis
- When building order-flow-imbalance or whale-pattern signals

## Inputs
- `symbol`: string — Ticker symbol
- `tape_data`: object[] — Time series of trades: {timestamp, price, size, side}
- `order_book_snapshots`: object[] — Optional: L2 snapshots for imbalance
- `lookback_minutes`: number — Window for analysis (default: 60)
- `min_iceberg_size`: number — Minimum shares to consider iceberg (default: 5000)
- `sensitivity`: number — Sensitivity 0–1 (default: 0.7)

## Outputs
- `icebergs_detected`: object[] — [{side, estimated_size, start_time, confidence}]
- `aggregate_buy_iceberg`: number — Estimated total buy iceberg size
- `aggregate_sell_iceberg`: number — Estimated total sell iceberg size
- `imbalance`: number — Net buy vs sell iceberg (positive = more buy)
- `confidence`: number — Overall detection confidence (0–1)
- `metadata`: object — symbol, lookback, method

## Steps
1. Load tape_data for lookback; filter by symbol
2. Group consecutive fills at same price/side with similar size (repeated small orders)
3. Detect "sawtooth" pattern: consistent small fills at regular intervals
4. Correlate with order book: large visible size that doesn't deplete suggests hidden
5. Estimate iceberg size: sum of fills in suspected cluster
6. Apply min_iceberg_size and sensitivity thresholds
7. Aggregate buy vs sell icebergs; compute imbalance
8. Return icebergs_detected, aggregate_buy_iceberg, aggregate_sell_iceberg, imbalance, confidence, metadata

## Example
```
Input: symbol="AAPL", lookback_minutes=60, min_iceberg_size=5000
Output: {
  icebergs_detected: [
    {side: "buy", estimated_size: 15000, start_time: "2025-03-03T14:30:00Z", confidence: 0.85},
    {side: "sell", estimated_size: 8000, start_time: "2025-03-03T14:45:00Z", confidence: 0.72}
  ],
  aggregate_buy_iceberg: 15000,
  aggregate_sell_iceberg: 8000,
  imbalance: 7000,
  confidence: 0.78,
  metadata: {symbol: "AAPL", lookback: 60, method: "tape_sawtooth"}
}
```

## Notes
- Heuristic: icebergs show as repeated small fills; not 100% accurate
- Use with order-flow-imbalance and toxic-flow-detector for confirmation
- Different from iceberg-order-sim (which executes icebergs); this detects them
