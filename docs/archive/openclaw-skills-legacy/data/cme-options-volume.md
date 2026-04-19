# CME 0DTE Options Volume & Open Interest

## Purpose
Fetch CME 0DTE (zero days to expiration) options volume and open interest for index futures options (ES, NQ, etc.) to assess short-dated flow.

## Category
data

## API Integration
- Provider: CME Group; CME DataMine or vendor (e.g., Databento, Polygon); Auth varies; Real-time and historical; Cost tier varies by vendor

## Triggers
- When agent needs 0DTE options volume or OI
- When user requests CME options flow, 0DTE, or index options
- When building flow signals from short-dated index options
- When assessing dealer gamma from 0DTE positioning

## Inputs
- `underlying`: string[] — "ES", "NQ", "RTY", "MES" (optional)
- `expiry`: string — Expiration date (optional; default: today for 0DTE)
- `data_type`: string — "volume", "oi", "both" (default: both)
- `strike_range`: object — {min, max} in index points (optional)
- `start`: string — ISO date for historical (optional)
- `end`: string — ISO date for historical (optional)

## Outputs
- `volume`: object — Per strike: call volume, put volume, total
- `open_interest`: object — Per strike: call OI, put OI, total
- `aggregate`: object — Total volume, total OI, put/call ratio
- `metadata`: object — Underlying, expiry, source, fetched_at

## Steps
1. Connect to CME options data via configured vendor
2. Filter for 0DTE (expiry = today) or specified expiry
3. Fetch volume and OI by strike for calls and puts
4. Aggregate total volume and OI
5. Compute put/call ratio for volume and OI
6. Filter by strike_range if provided
7. For historical: aggregate over start/end
8. Return volume, OI, aggregate, metadata
9. Cache with 15m TTL; 0DTE updates intraday

## Example
```
Input: underlying=["ES","NQ"], data_type="both", expiry="2025-03-03"
Output: {
  volume: {ES: {5900: {call:12000,put:8500}, 5910: {call:9500,put:11000}}, NQ: {...}},
  open_interest: {ES: {5900: {call:25000,put:18000}}},
  aggregate: {ES: {total_volume: 450000, total_oi: 890000, put_call_ratio: 0.92}},
  metadata: {underlying:["ES","NQ"], expiry:"2025-03-03", source:"cme", fetched_at:"2025-03-03T15:00:00Z"}
}
```

## Notes
- 0DTE options expire same day; data most relevant pre-close
- CME DataMine free for delayed; real-time requires subscription
- Vendor APIs (Databento, Polygon) may have different schemas
