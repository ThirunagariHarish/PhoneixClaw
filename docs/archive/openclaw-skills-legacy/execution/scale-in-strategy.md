# Scale-In Strategy

## Purpose
Scale into positions incrementally at predefined price levels or time intervals to reduce average entry cost and limit timing risk.

## Category
execution

## Triggers
- When the agent needs to build a scale-in (DCA or ladder) entry plan
- When user requests scale-in or dollar-cost averaging
- When entering large positions without moving the market
- When reducing single-entry timing risk

## Inputs
- `symbol`: string — Ticker
- `side`: string — "buy" or "sell"
- `total_quantity`: number — Total shares/contracts to accumulate
- `method`: string — "price_levels", "time_intervals", "percent_decline"
- `levels`: object[] — For price_levels: [{price, pct_of_total}]; for percent_decline: [{pct_drop, pct_of_total}]
- `interval_minutes`: number — For time_intervals: minutes between orders
- `current_price`: number — Current price for level calculation
- `max_duration_hours`: number — Max time to complete scale-in (optional)

## Outputs
- `orders`: object[] — Array of order specs with price, quantity, trigger condition
- `schedule`: object[] — For time-based: timestamps and quantities
- `avg_entry_target`: number — Weighted average target entry price
- `validation`: object — Pass/fail, total quantity check
- `metadata`: object — Method, levels_count, computed_at

## Steps
1. Validate total_quantity and levels sum to 100% or quantities sum correctly
2. If method=price_levels: compute quantity per level from pct_of_total
3. If method=percent_decline: compute trigger prices as current * (1 - pct_drop/100)
4. If method=time_intervals: divide total_quantity by number of intervals; build schedule
5. Build orders array: each with price/trigger, quantity, order_type
6. Compute avg_entry_target: weighted average of level prices
7. Validate: levels in logical order (buy: descending; sell: ascending)
8. Return orders, schedule (if time-based), avg_entry_target, validation, metadata
9. Pass orders to order-placer or schedule for time-based execution
10. Track filled quantity to avoid over-filling

## Example
```
Input: symbol="SPY", side="buy", total_quantity=300, method="percent_decline", levels=[{pct_drop: 0, pct_of_total: 40}, {pct_drop: 1, pct_of_total: 30}, {pct_drop: 2, pct_of_total: 30}], current_price=450
Output: {
  orders: [
    {price: 450, quantity: 120, trigger: "limit"},
    {price: 445.50, quantity: 90, trigger: "limit"},
    {price: 441, quantity: 90, trigger: "limit"}
  ],
  avg_entry_target: 446.10,
  validation: {pass: true},
  metadata: {method: "percent_decline", levels_count: 3, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Scale-in reduces timing risk but may leave unfilled if price never reaches levels
- Time-based scale-in is simpler but ignores price; use for DCA-style accumulation
- Ensure total orders do not exceed position limits or margin
