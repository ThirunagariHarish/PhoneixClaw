# Short Interest Fetch

## Purpose
Fetch short interest, days to cover, and short squeeze metrics for sentiment and contrarian analysis.

## Category
data

## Triggers
- When agent needs short interest data for squeeze potential
- When user requests short interest, days to cover, or short squeeze candidates
- When building contrarian plays or validating squeeze setups
- When assessing crowded short risk or borrow cost

## Inputs
- `symbols`: string[] — Tickers to look up (string[])
- `metrics`: string[] — "short_interest", "days_to_cover", "short_pct_float", "borrow_fee" (string[])
- `provider`: string — "finra", "exchange", "s3", "quiver", or default (string)
- `as_of_date`: string — Report date (string, optional)

## Outputs
- `short_interest`: object — Shares sold short per symbol (object)
- `days_to_cover`: object — Short interest / avg daily volume (object)
- `short_pct_float`: object — Short interest as % of float (object)
- `borrow_fee`: object — Cost to borrow % (object, if available)
- `metadata`: object — Report date, source, symbol count (object)

## Steps
1. Resolve short interest provider (FINRA, exchange, S3, Quiver)
2. Fetch short interest report for symbols (typically bi-monthly: mid and end of month)
3. Parse short interest: total shares sold short
4. Compute days_to_cover = short_interest / avg_daily_volume (need volume data)
5. Compute short_pct_float = short_interest / float (need float from fundamentals)
6. Fetch borrow fee from prime broker data if provider supports
7. Normalize units: short_interest in shares, days_to_cover in days, short_pct_float in %
8. Handle as_of_date: use latest report if not specified
9. Cache; short interest updates 2x per month
10. Return structured output with requested metrics and metadata

## Example
```
Input: symbols=["GME","AMC","BBBY"], metrics=["short_interest","days_to_cover","short_pct_float"]
Output: {
  short_interest: {GME: 45000000, AMC: 120000000, BBBY: 0},
  days_to_cover: {GME: 5.2, AMC: 3.1, BBBY: null},
  short_pct_float: {GME: 22.5, AMC: 18.3, BBBY: null},
  metadata: {report_date: "2025-02-28", source: "finra"}
}
```

## Notes
- Short interest is reported with 2-4 day lag
- Days to cover uses average volume; spikes can change quickly
- High short % float + high DTC = squeeze potential but also high risk
