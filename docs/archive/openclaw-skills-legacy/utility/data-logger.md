# Skill: Data Logger

## Purpose
Log structured data (prices, signals, orders, metrics) to persistent storage for backtesting, auditing, and analytics.

## Triggers
- When the agent needs to persist trade or signal data
- When user requests logging of specific events
- When execution or position changes occur
- When building audit trails or research datasets

## Inputs
- `event_type`: string — "trade", "signal", "order", "position", "metric", "custom"
- `payload`: object — Event data (symbol, price, qty, etc.)
- `tags`: string[] — Optional tags for filtering (e.g., ["strategy_a", "live"])
- `ttl_days`: number — Optional retention in days (default: config)
- `destination`: string — "db", "file", "s3", or default from config

## Outputs
- `logged`: boolean — Whether write succeeded
- `id`: string — Log entry ID or file path
- `error`: string — Error message if failed
- `metadata`: object — Timestamp, event_type, destination

## Steps
1. Validate event_type and payload schema
2. Add timestamp, agent_id, instance_id to payload
3. Resolve destination from input or config
4. For db: insert into events/audit table with tags
5. For file: append to daily log file (JSON lines)
6. For s3: write to bucket with date prefix
7. Apply TTL or retention policy if configured
8. Return logged status, id, and any error
9. Handle backpressure if write queue is full

## Example
```
Input: event_type="order", payload={symbol: "NVDA", side: "buy", qty: 50, status: "filled"}, tags=["live"]
Output: {
  logged: true,
  id: "evt_abc123",
  error: null,
  metadata: {timestamp: "2025-03-03T15:05:00Z", destination: "db"}
}
```
