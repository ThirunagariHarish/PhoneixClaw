# Sleep Mode Optimizer

## Purpose
Shut down agents during low-liquidity hours (8PM-4AM ET) to save resources and avoid thin-market traps.

## Category
utility

## Triggers
- On system startup to set initial sleep schedule
- On clock tick (e.g., every 15 min) to check enter/exit sleep
- When user overrides schedule (e.g., trade overnight futures)
- When market holiday or early close detected

## Inputs
- `schedule`: object — {sleep_start: "20:00", sleep_end: "04:00", timezone: "America/New_York"}
- `exceptions`: object[] — Optional; [{date, reason, active: true}] for override
- `grace_period_minutes`: number — Buffer before/after (default: 15)
- `instruments`: string[] — Optional; futures may need 24h coverage

## Outputs
- `is_sleeping`: boolean — True if agents should be dormant
- `next_wake`: string — ISO timestamp of next wake time
- `next_sleep`: string — ISO timestamp of next sleep time
- `reason`: string — "scheduled" | "exception" | "holiday" | "override"

## Steps
1. Load schedule; resolve timezone (e.g., America/New_York)
2. Get current time in that timezone
3. Check exceptions: if today in exceptions and active=false, skip sleep
4. If current time in [sleep_start - grace, sleep_end + grace]: is_sleeping=true
5. Compute next_wake (sleep_end) and next_sleep (next day sleep_start)
6. Handle market holidays: extend sleep or use holiday calendar
7. Return is_sleeping, next_wake, next_sleep, reason
8. Orchestrator uses is_sleeping to pause agent loops and data feeds

## Example
```
Input: schedule={sleep_start:"20:00", sleep_end:"04:00", timezone:"America/New_York"}
Output: {
  is_sleeping: true,
  next_wake: "2025-03-04T04:00:00-05:00",
  next_sleep: "2025-03-04T20:00:00-05:00",
  reason: "scheduled"
}
```

## Notes
- Crypto and forex may need different schedules (24h or session-based)
- Consider pre-market (4AM-9:30AM) as optional reduced-activity window
- Integrate with latency-monitor: no metrics during sleep
