# Iceberg Order Simulator

## Purpose
Simulate iceberg (display) orders for large positions by splitting total quantity into visible and hidden portions to minimize market impact and information leakage.

## Category
execution

## Triggers
- When the agent needs to simulate or plan iceberg order execution
- When user requests iceberg or display order strategy
- When placing large orders that could move the market
- When minimizing footprint in order book

## Inputs
- `symbol`: string — Ticker
- `side`: string — "buy" or "sell"
- `total_quantity`: number — Total shares/contracts to execute
- `display_quantity`: number — Visible quantity per slice (iceberg tip)
- `slice_interval_seconds`: number — Seconds between slice submissions (default: 5)
- `order_type`: string — "limit", "market" (limit preferred for iceberg)
- `limit_price`: number — Limit price for limit orders (optional)
- `max_slices`: number — Max number of slices (optional; default: total/display)

## Outputs
- `slices`: object[] — Array of slice specs: {quantity, display_qty, submit_after_sec}
- `total_slices`: number — Number of slices
- `estimated_duration_sec`: number — Total time to submit all slices
- `impact_estimate`: object — Estimated market impact (if model available)
- `metadata`: object — Symbol, total_quantity, display_quantity, computed_at

## Steps
1. Validate total_quantity and display_quantity; display must be <= total
2. Compute number of slices: ceil(total_quantity / display_quantity)
3. Build slices: each with quantity=display_quantity (last slice may be remainder)
4. Assign submit_after_sec: 0, slice_interval, 2*interval, ... for each slice
5. Compute estimated_duration_sec: (total_slices - 1) * slice_interval_seconds
6. Optionally estimate market impact using TWAP/VWAP model or historical spread
7. Return slices, total_slices, estimated_duration_sec, impact_estimate, metadata
8. Pass slices to execution layer for timed submission
9. Track filled quantity; adjust remaining slices if partial fills
10. Ensure broker supports display quantity (e.g., Alpaca extended hours, IBKR)

## Example
```
Input: symbol="AAPL", side="buy", total_quantity=5000, display_quantity=100, slice_interval_seconds=10, order_type="limit", limit_price=175.50
Output: {
  slices: [
    {quantity: 100, display_qty: 100, submit_after_sec: 0},
    {quantity: 100, display_qty: 100, submit_after_sec: 10},
    ... (50 slices)
  ],
  total_slices: 50,
  estimated_duration_sec: 490,
  impact_estimate: {estimated_slippage_bps: 5, twap_deviation_pct: 0.02},
  metadata: {symbol: "AAPL", total_quantity: 5000, display_quantity: 100, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Not all brokers support display quantity; may need to simulate with timed limit orders
- Slice interval should consider liquidity; too fast may still cause impact
- Combine with smart-order-router for optimal execution across venues
