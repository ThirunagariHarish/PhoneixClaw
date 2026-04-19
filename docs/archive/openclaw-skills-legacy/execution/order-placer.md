# Skill: Order Placer

## Purpose
Place orders through the execution queue to brokers (Alpaca, IBKR, etc.) with proper validation, idempotency, and status tracking.

## Triggers
- When the agent needs to submit an order to the market
- When user requests order placement or execution
- When trade-intent-generator output is ready for execution
- When bracket-order-builder produces orders to submit

## Inputs
- `intent`: object — Trade intent: symbol, side, quantity, order_type, limit_price, stop_loss, take_profit
- `broker`: string — "alpaca", "ibkr", or default from config
- `dry_run`: boolean — If true, validate but do not submit (default: false)
- `idempotency_key`: string — Optional; prevent duplicate submissions

## Outputs
- `order_id`: string — Broker-assigned order ID
- `status`: string — "submitted", "pending", "filled", "rejected"
- `fill_price`: number — Average fill price if partially/fully filled
- `error`: string — Error message if rejected or failed
- `metadata`: object — Broker, submitted_at, intent_hash

## Steps
1. Validate intent: symbol, side, quantity, order_type; check market hours if applicable
2. Resolve broker client from config; ensure credentials available
3. Map intent to broker order format: Alpaca (order object), IBKR (Contract, Order)
4. If bracket: submit parent + child orders (stop, target) as OCA or separate
5. Generate idempotency_key from intent hash if not provided
6. Check idempotency store: skip if same key already submitted recently
7. If dry_run: return simulated order_id and status "dry_run"
8. Submit order via broker API; capture order_id and initial status
9. Store in execution queue/DB for tracking; emit event for downstream
10. Return order_id, status, fill_price (if any), error, metadata

## Example
```
Input: intent={symbol: "NVDA", side: "buy", quantity: 50, order_type: "limit", limit_price: 875}, dry_run=false
Output: {
  order_id: "ord_abc123",
  status: "submitted",
  fill_price: null,
  error: null,
  metadata: {broker: "alpaca", submitted_at: "2025-03-03T15:00:05Z"}
}
```
