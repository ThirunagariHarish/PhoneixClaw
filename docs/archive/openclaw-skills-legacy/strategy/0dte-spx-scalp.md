# 0DTE SPX Scalp

## Purpose
Intraday 0DTE SPX options scalping using gamma levels, delta-neutral rebalancing, and quick profit targets.

## Category
strategy

## Triggers
- When SPX approaches a gamma-heavy strike (high OI)
- When 1–5 min momentum confirms direction
- During first 2 hours or last 2 hours of session

## Inputs
- spxPrice: current SPX level (number)
- gammaLevels: strikes with high gamma OI (array)
- momentum1m: 1-min price change (number)
- momentum5m: 5-min price change (number)
- ivRank: implied vol rank 0–100 (number)

## Outputs
- signal: LONG_CALL | LONG_PUT | FLAT (string)
- strike: recommended strike (number)
- targetTicks: profit target in ticks (number)
- stopTicks: stop loss in ticks (number)
- holdMinutes: max hold time (number)

## Steps
1. Identify nearest gamma level above and below spot
2. Enter long call when momentum1m and momentum5m both positive, spot near/below gamma level
3. Enter long put when both negative, spot near/above gamma level
4. Target 5–15 ticks; stop 3–8 ticks; hold max 10–20 min
5. Avoid when IV rank > 70; theta burn too high for scalp

## Example
```yaml
inputs:
  spxPrice: 5850
  gammaLevels: [5840, 5850, 5860]
  momentum1m: 2.5
  momentum5m: 4.2
outputs:
  signal: LONG_CALL
  strike: 5850
  targetTicks: 12
  stopTicks: 6
  holdMinutes: 15
```

## Notes
- Use tight risk; 0DTE can go to zero quickly
- Prefer ATM or 1 strike OTM; avoid deep OTM for scalps
