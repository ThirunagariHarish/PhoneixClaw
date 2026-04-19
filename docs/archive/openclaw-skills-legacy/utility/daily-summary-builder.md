# Daily Summary Builder

## Purpose
Build daily trading summary reports aggregating P&L, trades, positions, and key metrics.

## Category
utility

## Triggers
- At end of trading day (configurable time)
- When user requests daily summary
- When scheduled report generation runs
- After all positions are closed for the day

## Inputs
- `date`: string — ISO date for summary (default: previous trading day)
- `account_id`: string — Account to summarize (optional)
- `include_trades`: boolean — Include trade list (default: true)
- `include_positions`: boolean — Include open positions (default: true)
- `format`: string — "json", "markdown", or "html"

## Outputs
- `summary`: object — Aggregated daily metrics
- `trades`: object[] — List of trades if requested
- `positions`: object[] — Open positions if requested
- `report_text`: string — Formatted report when format specified

## Steps
1. Resolve date and account scope
2. Fetch trades and positions from data store
3. Compute daily P&L, win rate, largest winner/loser
4. Aggregate by symbol, strategy, or sector if configured
5. Build summary object with all metrics
6. Format report_text if format is markdown or html
7. Return summary and optional trade/position lists

## Example
```
Input: date="2025-03-02", include_trades=true, format="markdown"
Output: {
  summary: {pnl: 1250, win_rate: 0.65, trades_count: 12},
  trades: [...],
  report_text: "## Daily Summary 2025-03-02\nP&L: $1,250..."
}
```

## Notes
- Uses trade-journal-entry data when available
- Respects timezone for day boundary
- Can be sent via notification-sender for alerts
