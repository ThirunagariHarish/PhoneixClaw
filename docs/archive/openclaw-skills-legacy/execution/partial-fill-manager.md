# Partial Fill Manager

## Purpose
Re-route the remainder of partially filled orders to alternate venues or strategies to complete execution.

## Category
execution

## Triggers
- When an order receives a partial fill and remainder is still open
- When primary venue liquidity is insufficient
- When user enables "partial fill re-route" in execution config

## Inputs
- `order_id`: string — Original order ID
- `symbol`: string — Ticker symbol
- `side`: string — "buy" or "sell"
- `original_quantity`: number — Total order size
- `filled_quantity`: number — Already filled amount
- `remaining_quantity`: number — Unfilled remainder
- `primary_venue`: string — Venue where partial fill occurred
- `alternate_venues`: string[] — Venues to try (e.g., ["dark_pool", "lit", "another_broker"])
- `strategy`: string — "immediate", "twap_remainder", "limit_at_best" (default: immediate)

## Outputs
- `routed`: boolean — Whether remainder was routed
- `child_order_ids`: string[] — IDs of new orders placed for remainder
- `venue_used`: string — Venue where remainder was sent
- `filled_quantity_total`: number — Cumulative fill after re-route
- `metadata`: object — order_id, strategy, venues_tried

## Steps
1. Receive partial fill event (fill_quantity, remaining_quantity)
2. If remaining_quantity < min_order_size: cancel remainder or leave as-is per config
3. Select strategy: immediate = market at next venue; twap = slice remainder; limit = post at best
4. For immediate: try alternate_venues in order until one accepts
5. For twap: use time-slice-execution on remainder
6. For limit: post limit at NBBO; if not filled in timeout, escalate
7. Track child orders; aggregate fills back to original order
8. Return routed, child_order_ids, venue_used, filled_quantity_total, metadata

## Example
```
Input: order_id="ord_001", symbol="TSLA", side="buy", original_quantity=1000, filled_quantity=400, remaining_quantity=600, primary_venue="lit", strategy="immediate"
Output: {
  routed: true,
  child_order_ids: ["ord_002"],
  venue_used: "dark_pool",
  filled_quantity_total: 600,
  metadata: {order_id: "ord_001", strategy: "immediate", venues_tried: ["dark_pool"]}
}
```

## Notes
- Avoid wash-sale: ensure re-route doesn't trigger unintended tax events
- Venue selection may depend on liquidity-check and dark-pool-router
- Some brokers auto-handle partials; check before implementing
