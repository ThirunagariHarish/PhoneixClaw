# Laddered Entry/Exit

## Purpose
Average cost by entering or exiting in percentage tranches (e.g., 25/25/25/25) over time or price levels.

## Category
execution

## Triggers
- When user wants dollar-cost averaging or scaled entry/exit
- When strategy specifies tranched execution (e.g., 4 tranches at 25% each)
- When reducing single-trade impact via staggered orders

## Inputs
- `intent`: object — {symbol, side, total_quantity, order_type}
- `tranches`: number[] — Percentage per tranche (e.g., [25,25,25,25]) or count (e.g., 4 → equal)
- `trigger_type`: string — "time" (interval), "price" (levels), "hybrid"
- `time_interval_minutes`: number — Minutes between tranches (if trigger_type=time)
- `price_levels`: number[] — Price levels for each tranche (if trigger_type=price)
- `start_immediately`: boolean — Execute first tranche now (default: true)

## Outputs
- `schedule`: object[] — [{tranche, pct, quantity, trigger_time_or_price, order_id?}]
- `total_quantity`: number — Sum across tranches
- `executed_count`: number — Tranches already filled
- `metadata`: object — tranches, trigger_type, created_at

## Steps
1. Normalize tranches: if single number (e.g., 4), expand to [25,25,25,25]
2. Compute quantity per tranche: total_quantity * (pct/100)
3. If trigger_type=time: build schedule with time_interval_minutes between tranches
4. If trigger_type=price: sort by side (buy=asc, sell=desc); assign price_levels
5. Execute first tranche if start_immediately
6. Place remaining tranches at scheduled times or when price hits levels
7. Track fills; update executed_count
8. Return schedule, total_quantity, executed_count, metadata

## Example
```
Input: intent={symbol: "SPY", side: "buy", total_quantity: 400}, tranches=[25,25,25,25], trigger_type="time", time_interval_minutes=15
Output: {
  schedule: [
    {tranche: 1, pct: 25, quantity: 100, trigger_time_or_price: "2025-03-03T15:00:00Z", order_id: "ord_1"},
    {tranche: 2, pct: 25, quantity: 100, trigger_time_or_price: "2025-03-03T15:15:00Z"},
    ...
  ],
  total_quantity: 400,
  executed_count: 1,
  metadata: {tranches: [25,25,25,25], trigger_type: "time", created_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Price tranches require real-time price monitoring (hidden-stop-loss style)
- Integrate with scale-in-strategy and scale-out-strategy for consistency
- Time tranches can use time-slice-execution internally
