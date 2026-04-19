# Smart Router

## Purpose
Route orders to the optimal venue or broker based on latency, fill rate, and cost to achieve best execution.

## Category
execution

## Triggers
- When placing orders and multiple venues (Alpaca, IBKR, etc.) are available
- When user requests best execution or venue optimization
- When order size warrants venue selection analysis
- When comparing broker costs or fill quality across venues

## Inputs
- `intent`: object — Trade intent: symbol, side, quantity, order_type
- `urgency`: string — "immediate", "normal", "patient"
- `venues`: string[] — Available venues to consider (default: all configured)
- `latency_priority`: boolean — Prefer lowest-latency venue (default: false)
- `cost_priority`: boolean — Prefer lowest-cost venue (default: true)
- `fill_rate_history`: object — Optional: per-venue fill rate stats

## Outputs
- `selected_venue`: string — Chosen venue (e.g., "alpaca", "ibkr")
- `routing_reason`: string — Rationale for selection
- `estimated_fill_rate`: number — Expected fill probability (0–1)
- `estimated_cost_bps`: number — Estimated cost in basis points
- `metadata`: object — Venues evaluated, scores, latency_ms

## Steps
1. Fetch current quotes and spread for symbol from each venue
2. Query fill-rate history per venue for symbol/size (if available)
3. Compute latency score: ping each venue or use cached latency
4. Compute cost score: commissions, fees, spread impact per venue
5. Apply weights: latency_priority vs cost_priority
6. For urgency "immediate": boost latency weight; for "patient": boost cost weight
7. Rank venues by composite score
8. Select top venue; record routing_reason
9. Return selected_venue, routing_reason, estimated_fill_rate, estimated_cost_bps, metadata
10. Pass to order-placer for execution on selected venue

## Example
```
Input: intent={symbol: "SPY", side: "buy", quantity: 100}, urgency="normal", cost_priority=true
Output: {
  selected_venue: "alpaca",
  routing_reason: "Lowest spread (2 bps), 98% fill rate, zero commission",
  estimated_fill_rate: 0.98,
  estimated_cost_bps: 2,
  metadata: {venues_evaluated: ["alpaca", "ibkr"], alpaca_score: 0.95, ibkr_score: 0.82}
}
```

## Notes
- Requires venue connectivity and fill-rate telemetry
- Latency measurement may add 10–50ms; use cached values when acceptable
- Fallback to default venue if scoring fails
