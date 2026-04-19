# FRED Economic Data

## Purpose
Fetch Federal Reserve Economic Data (CPI, GDP, unemployment, Fed funds rate) from FRED API for macro and regime analysis.

## Category
data

## API Integration
- Provider: Federal Reserve FRED; REST API; API key in query param `api_key=`; 120 req/min; Free

## Triggers
- When agent needs macroeconomic indicators
- When user requests CPI, GDP, unemployment, Fed funds rate
- When building macro regime or economic calendar signals
- When assessing rate environment for strategy selection

## Inputs
- `series_ids`: string[] — FRED series (e.g., CPIAUCSL, GDP, UNRATE, FEDFUNDS)
- `start`: string — ISO date (optional)
- `end`: string — ISO date (optional)
- `frequency`: string — "d", "w", "m", "q", "a" (optional; some series fixed)
- `transform`: string — "lin", "chg", "pch" (optional)

## Outputs
- `observations`: object — Series ID -> [{date, value}, ...]
- `metadata`: object — Series info, units, frequency, source

## Steps
1. Call FRED /series/observations endpoint
2. Add api_key query param
3. Request each series_id; batch if API supports
4. Parse observations: date, value
5. Apply frequency/transform if specified
6. Sort by date ascending
7. Return observations dict and series metadata
8. Cache with 1d TTL; economic data updates daily/weekly/monthly

## Example
```
Input: series_ids=["CPIAUCSL","FEDFUNDS","UNRATE"], start="2024-01-01"
Output: {
  observations: {
    CPIAUCSL: [{date:"2024-01-01",value:308.4},{date:"2024-02-01",value:310.2}],
    FEDFUNDS: [{date:"2024-01-01",value:5.33}],
    UNRATE: [{date:"2024-01-01",value:3.7}]
  },
  metadata: {source:"fred", units: {CPIAUCSL:"Index", FEDFUNDS:"Percent"}}
}
```

## Notes
- Common series: CPIAUCSL (CPI), GDP, UNRATE, FEDFUNDS, DGS10 (10Y yield)
- Release schedules vary; check FRED release calendar
- 120 req/min sufficient for typical use
