# Backtest Report Gen

## Purpose
Generate backtest result reports with performance metrics, equity curve, and trade statistics.

## Category
utility

## Triggers
- When a backtest run completes
- When user requests backtest report for a run
- When comparing multiple backtest configurations
- When exporting results for documentation

## Inputs
- `backtest_id`: string — Backtest run identifier
- `format`: string — "json", "markdown", "html", or "pdf"
- `sections`: string[] — Sections to include (e.g., "metrics", "trades", "equity_curve")
- `include_trades`: boolean — Include full trade list (default: false for large runs)

## Outputs
- `report`: object — Structured report data
- `report_text`: string — Formatted report when format specified
- `metrics`: object — Key metrics (Sharpe, max drawdown, win rate)
- `metadata`: object — Backtest config, date range, symbol

## Steps
1. Load backtest results by backtest_id
2. Compute performance metrics (Sharpe, Sortino, max DD, CAGR)
3. Build equity curve and drawdown series
4. Aggregate trade statistics (win rate, avg hold, profit factor)
5. Assemble report object with requested sections
6. Format report_text for markdown/html/pdf
7. Return report and metrics

## Example
```
Input: backtest_id="BT-20250301-001", format="markdown", sections=["metrics","trades"]
Output: {
  report: {...},
  metrics: {sharpe: 1.42, max_drawdown: -0.08, win_rate: 0.58},
  report_text: "## Backtest Report\n### Metrics\nSharpe: 1.42..."
}
```

## Notes
- Large backtests may exclude full trade list by default
- PDF requires external renderer if configured
- Supports multi-strategy comparison reports
