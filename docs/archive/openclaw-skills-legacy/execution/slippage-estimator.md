# Skill: Slippage Estimator

## Purpose
Estimate expected slippage for a given order size based on current liquidity, spread, and historical fill data to inform execution decisions.

## Triggers
- When the agent needs slippage estimate for order sizing or routing
- When user requests slippage estimation
- When smart-order-router evaluates execution quality
- When assessing market impact before large orders

## Inputs
- `symbol`: string — Ticker to estimate
- `side`: string — "buy" or "sell"
- `quantity`: number — Order size in shares
- `order_type`: string — "market" or "limit"
- `use_historical`: boolean — Use historical fill data if available (default: true)

## Outputs
- `estimated_slippage_bps`: number — Expected slippage in basis points
- `estimated_slippage_dollars`: number — Expected dollar impact
- `confidence`: number — Estimate confidence 0-1
- `metadata`: object — Spread, depth_used, model

## Steps
1. Fetch current quote: bid, ask, spread, bid_size, ask_size
2. Fetch order book depth if available (levels 1-5)
3. Compute spread_bps = (ask - bid) / mid * 10000
4. For market order: base slippage = half spread (mid execution) + impact
5. Estimate impact: quantity vs available liquidity; square-root impact model if large
6. Impact_bps = k * sqrt(quantity / avg_daily_volume) * 10000; k from config
7. If use_historical: lookup avg slippage for similar size from fill history
8. Blend model estimate with historical if both available
9. estimated_slippage_dollars = quantity * (estimated_slippage_bps / 10000) * mid_price
10. Return estimated_slippage_bps, estimated_slippage_dollars, confidence, metadata

## Example
```
Input: symbol="NVDA", side="buy", quantity=500, order_type="market"
Output: {
  estimated_slippage_bps: 12,
  estimated_slippage_dollars: 5.25,
  confidence: 0.75,
  metadata: {spread_bps: 6, depth_used: true, model: "sqrt_impact"}
}
```
