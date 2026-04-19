# Scale-Out Strategy

## Purpose
Scale out of positions at predefined profit targets or price levels to lock in gains incrementally and reduce exposure as price moves favorably.

## Category
execution

## Triggers
- When the agent needs to build a scale-out (profit-taking) exit plan
- When user requests scale-out or partial profit targets
- When exiting large positions without moving the market
- When taking profits at multiple levels

## Inputs
- `symbol`: string — Ticker
- `side`: string — "buy" or "sell" (exit side; opposite of position)
- `total_quantity`: number — Total shares/contracts to exit
- `method`: string — "price_levels", "percent_gain", "r_multiple"
- `levels`: object[] — [{price_or_pct, pct_of_total}] or [{r_multiple, pct_of_total}]
- `entry_price`: number — Average entry price for % gain or R calculation
- `stop_loss`: number — Stop price for R multiple (optional)
- `current_price`: number — Current price for validation

## Outputs
- `orders`: object[] — Array of limit order specs with price, quantity
- `avg_exit_target`: number — Weighted average target exit price
- `total_profit_target`: number — Total profit if all levels fill (optional)
- `validation`: object — Pass/fail, quantity check
- `metadata`: object — Method, levels_count, computed_at

## Steps
1. Validate total_quantity and levels sum to 100% or quantities sum correctly
2. If method=price_levels: use explicit prices; compute quantity per level
3. If method=percent_gain: compute target prices as entry * (1 + pct_gain/100) for long
4. If method=r_multiple: compute target as entry + (entry - stop) * r_multiple
5. Build orders array: limit orders at each target price with partial quantity
6. Compute avg_exit_target: weighted average of level prices
7. Compute total_profit_target: sum of (price - entry) * quantity per level (for long)
8. Validate: levels in logical order (long exit: ascending; short exit: descending)
9. Return orders, avg_exit_target, total_profit_target, validation, metadata
10. Pass to order-placer; consider OCO with stop-loss for remaining position

## Example
```
Input: symbol="NVDA", side="sell", total_quantity=100, method="percent_gain", levels=[{pct_gain: 2, pct_of_total: 33}, {pct_gain: 4, pct_of_total: 33}, {pct_gain: 6, pct_of_total: 34}], entry_price=875
Output: {
  orders: [
    {price: 892.50, quantity: 33, type: "limit"},
    {price: 910, quantity: 33, type: "limit"},
    {price: 927.50, quantity: 34, type: "limit"}
  ],
  avg_exit_target: 910.25,
  total_profit_target: 3525,
  validation: {pass: true},
  metadata: {method: "percent_gain", levels_count: 3, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Scale-out locks in gains but may leave upside if price continues
- Combine with trailing stop for remainder to capture extended moves
- Ensure partial fills are tracked; remaining quantity needs stop-loss
