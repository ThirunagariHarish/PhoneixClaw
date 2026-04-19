# Dark Pool Router

## Purpose
Route orders to dark pools to minimize market impact and information leakage for large or sensitive orders.

## Category
execution

## Triggers
- When placing orders where market impact is a concern
- When user requests dark pool routing or block trading
- When order size exceeds block threshold (e.g., 5% of ADV)
- When avoiding visible order book footprint is desired

## Inputs
- `intent`: object — Trade intent: symbol, side, quantity, order_type
- `dark_pools`: string[] — Available dark pools (e.g., ["sigma_x", "level_ats", "crossfinder"])
- `min_fill_pct`: number — Minimum expected fill % to use dark pool (default: 20)
- `max_wait_seconds`: number — Max time to wait for dark fill before routing to lit (default: 30)
- `allow_iso`: boolean — Allow intermarket sweep to lit if dark unfilled (default: true)

## Outputs
- `routing_decision`: object — {primary: "dark"|"lit", dark_pool, params}
- `expected_fill_pct`: number — Estimated dark pool fill probability
- `fallback_plan`: object — Lit venue and params if dark fails
- `metadata`: object — Dark pool liquidity estimate, last_fill_rates

## Steps
1. Fetch dark pool availability and recent fill rates for symbol
2. Estimate dark pool liquidity (e.g., from dark-pool-volume or venue API)
3. If expected_fill_pct < min_fill_pct: route to lit instead
4. Select best dark pool by fill rate and cost
5. Build dark order params: pegged to mid, hidden, IOC or TTL
6. Set max_wait_seconds; define fallback to lit if unfilled
7. Return routing_decision, expected_fill_pct, fallback_plan, metadata
8. Pass to order-placer; monitor fill; trigger fallback if timeout
9. Log dark vs lit fill results for optimization

## Example
```
Input: intent={symbol: "TSLA", side: "buy", quantity: 2000}, min_fill_pct=25
Output: {
  routing_decision: {primary: "dark", dark_pool: "sigma_x", params: {pegged: "mid", hidden: true}},
  expected_fill_pct: 35,
  fallback_plan: {venue: "alpaca", order_type: "limit", limit_price: "mid"},
  metadata: {sigma_x_fill_rate: 0.32, liquidity_estimate: 800}
}
```

## Notes
- Dark pool access requires broker support (IBKR, some institutional)
- Fill rates vary by symbol and time of day
- ISO (Intermarket Sweep Order) may be required for Reg NMS compliance
