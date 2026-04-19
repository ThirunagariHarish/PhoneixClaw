# Skill: Report Generator

## Purpose
Generate structured reports (daily P&L, performance summary, trade log, risk metrics) in text, markdown, or JSON format for review or export.

## Triggers
- When the agent needs to produce a performance report
- When user requests daily summary, trade log, or risk report
- When scheduled report (e.g., EOD) is due
- When exporting data for external tools

## Inputs
- `report_type`: string — "daily_pnl", "trade_log", "risk_summary", "performance", "custom"
- `start_date`: string — ISO date for report start
- `end_date`: string — ISO date for report end
- `format`: string — "text", "markdown", "json"
- `sections`: string[] — Optional sections to include (e.g., ["trades", "positions"])

## Outputs
- `report`: string — Generated report content
- `format`: string — Output format used
- `metadata`: object — Report type, date range, generated_at

## Steps
1. Resolve report_type and date range
2. Fetch data: trades, positions, P&L from data-logger or DB
3. For daily_pnl: aggregate P&L by day, open/close positions
4. For trade_log: list trades with symbol, side, qty, price, P&L
5. For risk_summary: max drawdown, exposure, VaR if available
6. For performance: returns, Sharpe, win rate, etc.
7. Format output per format: text (plain), markdown (headers, tables), json (structured)
8. Apply section filter if specified
9. Return report content, format, metadata

## Example
```
Input: report_type="daily_pnl", start_date="2025-03-01", end_date="2025-03-03", format="markdown"
Output: {
  report: "## Daily P&L Report\n\n### 2025-03-03\n- Realized P&L: $1,250\n- Open positions: 3\n...",
  format: "markdown",
  metadata: {report_type: "daily_pnl", start: "2025-03-01", end: "2025-03-03", generated_at: "2025-03-03T16:00:00Z"}
}
```
