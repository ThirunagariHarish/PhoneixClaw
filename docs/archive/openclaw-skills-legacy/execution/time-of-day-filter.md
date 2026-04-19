# Skill: Time of Day Filter

## Purpose
Filter trades based on market session timing (pre-market, regular, after-hours) to avoid low-liquidity periods or enforce session-specific rules.

## Triggers
- When the agent needs to check if a trade is allowed at current time
- When user requests session-based trade filtering
- When trade-intent-generator applies session constraints
- When eod-position-sweeper coordinates with market close

## Inputs
- `timestamp`: string — ISO timestamp to check (default: now)
- `symbol`: string — For exchange/market hours (US equities default)
- `allowed_sessions`: string[] — ["pre", "regular", "after"] or subset
- `avoid_first_minutes`: number — Skip first N minutes of regular session (default: 0)
- `avoid_last_minutes`: number — Skip last N minutes before close (default: 0)

## Outputs
- `allowed`: boolean — Whether trade is allowed at given time
- `current_session`: string — "pre", "regular", "after", or "closed"
- `minutes_to_open`: number — Minutes until regular session open (if closed)
- `minutes_to_close`: number — Minutes until regular session close (if in session)
- `metadata`: object — Market, timezone, timestamp_checked

## Steps
1. Parse timestamp; resolve to market timezone (US/Eastern for US equities)
2. Define session boundaries: pre (4:00-9:30 ET), regular (9:30-16:00 ET), after (16:00-20:00 ET)
3. Determine current_session from timestamp
4. If current_session not in allowed_sessions: allowed = false
5. If in regular session: check avoid_first_minutes (after 9:30) and avoid_last_minutes (before 16:00)
6. Compute minutes_to_open: if before 9:30, else 0; minutes_to_close: if in regular, else 0
7. Handle holidays: use exchange calendar; if holiday, current_session = "closed"
8. Return allowed, current_session, minutes_to_open, minutes_to_close, metadata
9. Integrate with trade flow: reject intent if allowed = false
10. Log session checks for debugging

## Example
```
Input: timestamp="2025-03-03T14:30:00Z", allowed_sessions=["regular"], avoid_last_minutes=15
Output: {
  allowed: true,
  current_session: "regular",
  minutes_to_open: 0,
  minutes_to_close: 90,
  metadata: {market: "US", timezone: "America/New_York"}
}
```
