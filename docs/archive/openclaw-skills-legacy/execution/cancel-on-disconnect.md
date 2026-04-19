# Cancel on Disconnect

## Purpose
Auto-cancel all open orders when connection to the broker drops to prevent orphaned orders.

## Category
execution

## Triggers
- When broker WebSocket/API connection is lost or times out
- When heartbeat/ping fails for N consecutive attempts
- When user enables "cancel on disconnect" safety mode
- On graceful shutdown of trading process

## Inputs
- `connection_status`: string — "disconnected", "timeout", "heartbeat_fail"
- `open_orders`: object[] — List of order IDs and symbols (or fetch from broker)
- `cancel_all`: boolean — Cancel all orders vs only specific symbols (default: true)
- `symbol_filter`: string[] — Optional: only cancel orders for these symbols
- `order_types`: string[] — Optional: ["limit", "stop", "stop_limit"] to cancel (default: all)

## Outputs
- `cancelled_count`: number — Number of orders successfully cancelled
- `cancelled_order_ids`: string[] — IDs of cancelled orders
- `failed_cancels`: object[] — [{order_id, error}] for any failures
- `metadata`: object — connection_status, timestamp, broker

## Steps
1. Detect connection loss via WebSocket close, timeout, or heartbeat failure
2. Fetch open orders from broker (or use provided open_orders)
3. Apply symbol_filter and order_types if specified
4. For each order: call broker cancel API
5. Track successes and failures; retry failed cancels once
6. Log all cancellations for audit trail
7. Return cancelled_count, cancelled_order_ids, failed_cancels, metadata
8. Optionally notify user/alert system of disconnect and cancellations

## Example
```
Input: connection_status="disconnected", cancel_all=true
Output: {
  cancelled_count: 5,
  cancelled_order_ids: ["ord_001", "ord_002", "ord_003", "ord_004", "ord_005"],
  failed_cancels: [],
  metadata: {connection_status: "disconnected", timestamp: "2025-03-03T15:00:00Z", broker: "ibkr"}
}
```

## Notes
- Must run before any reconnection logic; avoid duplicate cancels
- Some brokers auto-cancel on disconnect; check broker docs
- Consider persisting "pending cancel" state if broker unreachable
