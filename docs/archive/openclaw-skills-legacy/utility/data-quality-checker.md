# Data Quality Checker

## Purpose
Validate data quality and completeness for market data, positions, and trade records.

## Category
utility

## Triggers
- Before backtest or model training
- When ingesting new data feeds
- On scheduled data quality scans
- When user requests data validation

## Inputs
- `data_type`: string — "ohlcv", "positions", "trades", "fundamentals"
- `source`: string — Data source identifier
- `start_date`: string — Check period start (ISO)
- `end_date`: string — Check period end (ISO)
- `symbols`: string[] — Symbols to check (optional)
- `checks`: string[] — "missing", "gaps", "outliers", "duplicates"

## Outputs
- `passed`: boolean — Overall pass/fail
- `issues`: object[] — List of quality issues found
- `summary`: object — Count by issue type, coverage stats
- `recommendations`: string[] — Suggested fixes

## Steps
1. Load data for specified type, source, date range
2. Run requested checks: missing bars, gaps, outliers, duplicates
3. For OHLCV: check volume=0, price spikes, timestamp gaps
4. For positions/trades: check referential integrity
5. Aggregate issues and compute pass/fail
6. Generate recommendations for common issues
7. Return passed, issues, summary

## Example
```
Input: data_type="ohlcv", source="alpaca", start_date="2025-02-01", end_date="2025-02-28", checks=["gaps","outliers"]
Output: {
  passed: false,
  issues: [{symbol: "NVDA", date: "2025-02-15", type: "gap", detail: "Missing 3 bars"}],
  summary: {gaps: 1, outliers: 0, symbols_checked: 50},
  recommendations: ["Backfill NVDA 2025-02-15 from alternate source"]
}
```

## Notes
- Outlier thresholds configurable per symbol/asset
- Supports multiple data sources for cross-validation
- Integrates with data-logger for audit trail
