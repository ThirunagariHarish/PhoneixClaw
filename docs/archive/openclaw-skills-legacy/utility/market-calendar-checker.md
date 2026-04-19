# Skill: Market Calendar Checker

## Purpose
Check market hours, holidays, half-days, and special sessions (e.g., options expiration) to avoid trading during closed periods or low-liquidity windows.

## Triggers
- When the agent needs to verify market is open before execution
- When user asks about market hours or upcoming holidays
- When scheduling automated tasks or scans
- When validating order placement timing

## Inputs
- `query`: string — "hours", "holidays", "half_days", "expiration", or "next_open"
- `date`: string — ISO date to check (optional; default: today)
- `timezone`: string — Timezone for output (default: "America/New_York")
- `exchange`: string — "NYSE", "NASDAQ", or "all"

## Outputs
- `is_open`: boolean — Whether market is open at query time
- `next_open`: string — Next market open timestamp (if closed)
- `next_close`: string — Next market close timestamp (if open)
- `holidays`: object[] — Upcoming holidays in range
- `metadata`: object — Timezone, exchange, query time

## Steps
1. Load market calendar (NYSE/NASDAQ holidays, half-days)
2. Resolve query date and timezone
3. For "hours": return regular session 9:30–16:00 ET (extended if configured)
4. For "holidays": return list of holidays in next 30 days
5. For "expiration": return next options expiration (3rd Friday)
6. For "next_open": compute next open considering weekends and holidays
7. Return is_open, next_open, next_close, holidays as applicable
8. Cache calendar data with daily refresh

## Example
```
Input: query="next_open", date="2025-03-03"
Output: {
  is_open: true,
  next_open: "2025-03-03T09:30:00-05:00",
  next_close: "2025-03-03T16:00:00-05:00",
  holidays: [],
  metadata: {timezone: "America/New_York", exchange: "NYSE"}
}
```
