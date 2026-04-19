# Inflation Data Pause

## Purpose
Pause trading 30 minutes before major CPI/PPI releases to avoid whipsaw and gap risk.

## Category
advanced-ai

## Triggers
- On clock tick (e.g., every 5 min) to check economic calendar
- When CPI or PPI release is within 30 minutes
- When user requests economic calendar status
- Before market open on release days (8:30 AM ET typical)

## Inputs
- `economic_calendar`: object — Source (FRED, ForexFactory, or custom)
- `pause_minutes_before`: number — Minutes before release to pause (default: 30)
- `pause_minutes_after`: number — Minutes after to remain cautious (default: 15)
- `events`: string[] — Event types to pause for (default: ["CPI", "PPI", "FOMC", "NFP"])
- `timezone`: string — Calendar timezone (default: "America/New_York")

## Outputs
- `trading_paused`: boolean — True if within pause window
- `next_release`: object — {event, datetime, minutes_until}
- `pause_until`: string — ISO timestamp when pause ends
- `reason`: string — "CPI_RELEASE" | "PPI_RELEASE" | "NONE" | etc.

## Steps
1. Fetch economic calendar for next 24-48 hours
2. Filter for events in ["CPI", "PPI", "FOMC", "NFP"]
3. Find next upcoming release; compute minutes_until
4. If minutes_until <= pause_minutes_before: trading_paused=true
5. Set pause_until = release_time + pause_minutes_after
6. If current time < pause_until: trading_paused=true
7. Return trading_paused, next_release, pause_until, reason
8. Orchestrator blocks new entries during pause; may allow exits

## Example
```
Input: economic_calendar=client, pause_minutes_before=30, events=["CPI","PPI","FOMC","NFP"]
Output: {
  trading_paused: true,
  next_release: {event: "CPI", datetime: "2025-03-03T08:30:00-05:00", minutes_until: 18},
  pause_until: "2025-03-03T08:45:00-05:00",
  reason: "CPI_RELEASE"
}
```

## Notes
- CPI/PPI typically 8:30 AM ET; FOMC varies; NFP first Friday of month
- Consider reducing position size instead of full pause for swing positions
- Integrate with sleep-mode-optimizer for overnight releases
