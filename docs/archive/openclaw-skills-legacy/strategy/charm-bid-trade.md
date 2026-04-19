# Charm Bid Trade

## Purpose
Trade the quiet-day "charm bid" — upward drift as 0DTE dealers unwind hedges into expiration.

## Category
strategy

## Triggers
- On low-volatility days (VIX < 18)
- When 0DTE OI is elevated and time decay accelerates
- In final 2–4 hours before 0DTE expiration

## Inputs
- vix: current VIX level (number)
- odteOi: 0DTE open interest by strike (object)
- timeToExp: minutes to 0DTE expiry (number)
- spotPrice: current underlying price (number)
- realizedVol: 10-day realized vol (number)

## Outputs
- signal: LONG | FLAT (string)
- strength: 0–100 charm bid strength (number)
- windowStart: suggested entry window start (timestamp)
- windowEnd: suggested exit before expiry (timestamp)

## Steps
1. Filter: VIX < 18, timeToExp between 120–240 min
2. Sum dealer charm exposure: short calls lose delta, dealers buy spot to hedge
3. Compute charm bid strength from OI × charm (delta decay) by strike
4. Enter long when strength > 60; exit 30–60 min before expiry
5. Size smaller on high realized vol; charm effect muted

## Example
```yaml
inputs:
  vix: 14.5
  odteOi: {4500: 120000, 4510: 95000}
  timeToExp: 180
outputs:
  signal: LONG
  strength: 72
  windowStart: "2025-03-03T13:00:00Z"
  windowEnd: "2025-03-03T15:30:00Z"
```

## Notes
- Charm bid is subtle; avoid overtrading; 1–2 setups per day typical
- Fade or avoid on Fed/earnings days; macro events override charm
