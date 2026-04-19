# Performance Attribution

## Purpose
Attribute P&L to factors (sector, strategy, holding period) and strategies for analysis.

## Category
utility

## Triggers
- When user requests performance breakdown
- When evaluating strategy effectiveness
- When generating monthly/quarterly reports
- When comparing factor contributions

## Inputs
- `start_date`: string — Attribution period start (ISO)
- `end_date`: string — Attribution period end (ISO)
- `account_id`: string — Account to attribute (optional)
- `dimensions`: string[] — "strategy", "sector", "symbol", "holding_period"
- `benchmark`: string — Optional benchmark for excess return

## Outputs
- `attribution`: object — P&L by dimension
- `total_pnl`: number — Total P&L in period
- `breakdown`: object — Nested breakdown by each dimension
- `metadata`: object — Period, account, dimensions used

## Steps
1. Fetch trades and positions for date range
2. Map each trade to dimensions (strategy tag, sector, symbol)
3. Compute P&L contribution per dimension
4. Aggregate by holding period if requested
5. Compare to benchmark if provided
6. Return attribution object and breakdown

## Example
```
Input: start_date="2025-02-01", end_date="2025-02-28", dimensions=["strategy","sector"]
Output: {
  attribution: {strategy: {momentum: 1200, mean_reversion: -150}, sector: {tech: 800, finance: 250}},
  total_pnl: 1050,
  breakdown: {...},
  metadata: {period: "2025-02-01/2025-02-28"}
}
```

## Notes
- Requires strategy tags on trades for strategy attribution
- Sector from symbol metadata or external mapping
- Supports custom dimension definitions
