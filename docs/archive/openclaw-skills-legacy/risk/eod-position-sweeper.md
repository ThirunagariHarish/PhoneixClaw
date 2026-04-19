# Skill: EOD Position Sweeper

## Purpose
Auto-close positions before market close to avoid overnight risk, or flatten specific symbols/sectors per end-of-day rules.

## Triggers
- When the agent needs to execute EOD flattening or position sweeps
- When user requests EOD close or day-trade-only enforcement
- When time-of-day-filter indicates approaching market close
- When configured EOD rules require position reduction

## Inputs
- `positions`: object[] — Current positions to evaluate
- `close_time_minutes`: number — Minutes before close to start sweep (default: 15)
- `symbols_to_close`: string[] — Specific symbols (empty = all day-trade positions)
- `close_type`: string — "market", "limit", or "reduce_only"
- `dry_run`: boolean — If true, report what would be closed without executing (default: false)

## Outputs
- `orders_placed`: object[] — Order IDs and symbols closed
- `positions_closed`: object[] — Positions that were closed
- `skipped`: object[] — Positions skipped with reason
- `metadata`: object — Sweep_time, close_time, dry_run

## Steps
1. Check current time vs market close (16:00 ET); if within close_time_minutes, proceed
2. Filter positions: if symbols_to_close specified, only those; else all positions
3. Optionally filter by tag: "day_trade" or "eod_close" if position metadata has it
4. For each position, build close order: opposite side, same quantity
5. If close_type "limit": use current bid (long) or ask (short) or last - buffer
6. If dry_run: return list of would-close positions, no orders
7. Submit orders via order-placer; collect order_ids
8. Track positions_closed and skipped (e.g., symbol in exclude list)
9. Update position records; emit EOD sweep event
10. Return orders_placed, positions_closed, skipped, metadata

## Example
```
Input: positions=[{symbol: "NVDA", quantity: 50, side: "long"}], close_time_minutes=15, dry_run=false
Output: {
  orders_placed: [{symbol: "NVDA", order_id: "ord_close_456", side: "sell", quantity: 50}],
  positions_closed: [{symbol: "NVDA", quantity: 50}],
  skipped: [],
  metadata: {sweep_time: "2025-03-03T15:45:00Z", close_time: "16:00 ET", dry_run: false}
}
```
