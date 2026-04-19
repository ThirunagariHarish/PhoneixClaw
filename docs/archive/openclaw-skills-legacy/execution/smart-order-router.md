# Skill: Smart Order Router

## Purpose
Route orders for best execution by selecting venue, order type, and timing based on liquidity, spread, and execution objectives.

## Triggers
- When the agent needs to optimize order execution
- When user requests smart routing or best execution
- When placing large orders that may benefit from splitting or dark pools
- When minimizing market impact for institutional-sized orders

## Inputs
- `intent`: object — Trade intent: symbol, side, quantity, order_type
- `urgency`: string — "immediate", "normal", "patient"
- `max_slippage_bps`: number — Max acceptable slippage in basis points (default: 10)
- `venues`: string[] — Optional: ["alpaca", "ibkr", "dark_pool"] or default

## Outputs
- `routing_decision`: object — Venue, order_type, split_strategy
- `estimated_slippage_bps`: number — Expected slippage from slippage-estimator
- `metadata`: object — Liquidity checked, venues_considered

## Steps
1. Fetch current quote (bid/ask, spread) for symbol via market-data-fetcher
2. Estimate slippage using slippage-estimator for given quantity
3. If slippage > max_slippage_bps and quantity large: consider split (TWAP, VWAP)
4. For urgency "immediate": prefer market order or aggressive limit
5. For "patient": use limit at mid or better; consider dark pool if available
6. Select venue: prefer lowest spread, best fill history; check venue availability
7. Build routing_decision: venue, order_type, limit_price (if applicable), split_params
8. Return routing_decision, estimated_slippage_bps, metadata
9. Pass routing_decision to order-placer for execution
10. Log routing for execution quality analysis

## Example
```
Input: intent={symbol: "NVDA", side: "buy", quantity: 500}, urgency="normal", max_slippage_bps=15
Output: {
  routing_decision: {venue: "alpaca", order_type: "limit", limit_price: 875.10, split_strategy: null},
  estimated_slippage_bps: 8,
  metadata: {spread_bps: 5, venues_considered: ["alpaca", "ibkr"]}
}
```
