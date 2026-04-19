# US Treasury Yield Curve

## Purpose
Fetch US Treasury yield curve data (2Y, 5Y, 10Y, 30Y, etc.) from treasury.gov or FRED for rate environment and curve analysis.

## Category
data

## API Integration
- Provider: US Treasury (treasury.gov) or FRED; REST/CSV; No auth; Free; No explicit rate limit

## Triggers
- When agent needs Treasury yields or yield curve
- When user requests rates, yield curve, or bond yields
- When building rate-sensitive signals or regime analysis
- When assessing curve shape (steepness, inversion)

## Inputs
- `tenors`: string[] — "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y" (optional; default: all)
- `start`: string — ISO date for historical (optional)
- `end`: string — ISO date for historical (optional)
- `source`: string — "treasury", "fred" (default: treasury)

## Outputs
- `yields`: object — Tenor -> yield (percent)
- `curve`: object[] — [{tenor, yield, date}] for historical
- `spreads`: object — Key spreads: 2s10s, 2s30s, 10s30s
- `metadata`: object — Source, as_of date, fetched_at

## Steps
1. For treasury.gov: fetch XML/JSON daily yield curve
2. For FRED: use DGS2, DGS5, DGS10, DGS30 series
3. Parse yields by tenor (1M, 3M, 6M, 1Y, 2Y, 5Y, 10Y, 30Y)
4. Compute spreads: 2s10s = 10Y - 2Y, etc.
5. For historical: fetch time series over start/end
6. Return yields, curve, spreads, metadata
7. Cache with 1d TTL; Treasury updates daily
8. Handle FRED 120 req/min if using FRED

## Example
```
Input: tenors=["2Y","5Y","10Y","30Y"], source="treasury"
Output: {
  yields: {2Y: 4.52, 5Y: 4.28, 10Y: 4.35, 30Y: 4.50},
  curve: [{tenor:"2Y",yield:4.52,date:"2025-03-03"},{tenor:"10Y",yield:4.35,date:"2025-03-03"}],
  spreads: {2s10s: -0.17, 2s30s: -0.02, 10s30s: 0.15},
  metadata: {source:"treasury", as_of:"2025-03-03", fetched_at:"2025-03-03T14:00:00Z"}
}
```

## Notes
- Treasury.gov provides official daily curve
- FRED DGS* series: DGS2, DGS5, DGS10, DGS30
- Inverted curve (2s10s < 0) often recession signal
