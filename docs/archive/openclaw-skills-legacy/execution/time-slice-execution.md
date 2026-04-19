# Time-Slice Execution

## Purpose
TWAP execution: split a single order across time intervals to minimize market impact and achieve volume-weighted average price.

## Category
execution

## Triggers
- When placing large orders that would move the market
- When user requests TWAP, time-sliced, or scheduled execution
- When order size exceeds a configurable threshold (e.g., 10% of ADV)
- When minimizing market impact is the primary objective

## Inputs
- `intent`: object — Trade intent: symbol, side, quantity, order_type
- `duration_minutes`: number — Total execution window (e.g., 60)
- `slice_count`: number — Number of child orders (default: auto from duration)
- `slice_interval_seconds`: number — Seconds between slices (alternative to slice_count)
- `start_time`: string — ISO timestamp to begin (default: now)
- `randomize`: boolean — Add jitter to slice timing (default: true)
- `min_slice_size`: number — Minimum shares per slice (default: 1)

## Outputs
- `schedule`: object[] — Array of {time, quantity, limit_price} for each slice
- `total_quantity`: number — Sum of slice quantities (should match intent)
- `estimated_completion`: string — ISO timestamp of last slice
- `metadata`: object — Duration, slice_count, interval_seconds

## Steps
1. Validate quantity and duration; compute slice_count if not provided
2. Compute slice_interval = duration_minutes * 60 / slice_count
3. Distribute quantity across slices (equal or volume-weighted)
4. Enforce min_slice_size; merge tiny slices if needed
5. If randomize: add ±10% jitter to each slice time
6. Build schedule array with time, quantity per slice
7. Optionally fetch VWAP curve to weight slices by typical volume
8. Return schedule, total_quantity, estimated_completion, metadata
9. Execute slices via order-placer at scheduled times (or return for external scheduler)
10. Log execution for TWAP vs actual fill analysis

## Example
```
Input: intent={symbol: "AAPL", side: "sell", quantity: 5000}, duration_minutes=60, slice_count=12
Output: {
  schedule: [
    {time: "2025-03-03T14:00:00Z", quantity: 417, limit_price: null},
    {time: "2025-03-03T14:05:00Z", quantity: 417, limit_price: null},
    ...
  ],
  total_quantity: 5000,
  estimated_completion: "2025-03-03T15:00:00Z",
  metadata: {duration_minutes: 60, slice_count: 12, interval_seconds: 300}
}
```

## Notes
- Scheduler must respect market hours; adjust for pre/post market if configured
- VWAP weighting requires historical volume curve (e.g., from market-data-fetcher)
- Consider using limit orders at mid for each slice to control slippage
