# Bond Yield Fetch

## Purpose
Fetch treasury and corporate bond yields, curves, and spread data for fixed income analysis and macro signals.

## Category
data

## Triggers
- When agent needs bond yields for macro analysis or risk-off signals
- When user requests treasury rates, yield curve, or corporate spreads
- When building rate-sensitive strategies or duration hedging
- When validating recession signals (curve inversion) or Fed policy impact

## Inputs
- `instruments`: string[] — e.g. ["10Y","2Y","30Y","TIPS10"] or CUSIPs (string[])
- `data_type`: string — "yield", "curve", "spread", "price" (string)
- `benchmark`: string — For spreads: "treasury", "swap" (string, optional)
- `start`: string — ISO date for historical (string, optional)
- `end`: string — ISO date for historical (string, optional)
- `provider`: string — "fred", "treasury", "bloomberg", or default (string)

## Outputs
- `yields`: object — Yield % per instrument (object)
- `curve`: object[] — Maturity and yield for curve (object[])
- `spreads`: object — Spread vs benchmark in bps (object)
- `metadata`: object — Source, fetch time, data date (object)

## Steps
1. Resolve bond data provider (FRED, Treasury, Bloomberg API)
2. Map instrument names to provider symbols (e.g., 10Y → DGS10)
3. For yield: fetch current yield for each instrument
4. For curve: fetch full treasury curve (2Y, 5Y, 10Y, 30Y, etc.)
5. For spread: fetch corporate yield and subtract benchmark (e.g., 10Y treasury)
6. For historical: fetch time series over start/end
7. Normalize units: yields in %, spreads in bps
8. Handle provider-specific formats (e.g., FRED series IDs)
9. Cache with moderate TTL (yields change intraday but not tick-by-tick)
10. Return structured output with metadata

## Example
```
Input: instruments=["2Y","10Y","30Y"], data_type="curve"
Output: {
  curve: [{maturity: "2Y", yield: 4.52}, {maturity: "10Y", yield: 4.28}, {maturity: "30Y", yield: 4.45}],
  yields: {"2Y": 4.52, "10Y": 4.28, "30Y": 4.45},
  metadata: {source: "fred", fetched_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Treasury data often has 1-day lag for some providers
- Corporate bonds: use indices (e.g., ICE BofA) or specific CUSIPs
- Yield curve inversion (2Y-10Y) is a recession indicator
