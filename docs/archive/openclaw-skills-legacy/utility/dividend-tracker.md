# Dividend Tracker

## Purpose
Track dividend income and ex-dates for income reporting and tax planning.

## Category
utility

## Triggers
- When positions are held through ex-date
- When user requests dividend schedule
- When generating income reports
- When checking ex-date before trade execution

## Inputs
- `action`: string — "record", "schedule", "report", "check"
- `symbol`: string — Ticker symbol
- `amount`: number — Dividend amount (for record)
- `pay_date`: string — Payment date (ISO)
- `ex_date`: string — Ex-dividend date (ISO)
- `qualified`: boolean — Qualified dividend flag (for tax)
- `start_date`: string — Schedule/report start (optional)
- `end_date`: string — Schedule/report end (optional)

## Outputs
- `dividends`: object[] — Recorded or scheduled dividends
- `total_income`: number — Total dividend income in period
- `ex_dates`: object[] — Upcoming ex-dates for symbols
- `metadata`: object — Action, dates, symbol

## Steps
1. For "record": store dividend with symbol, amount, pay_date, ex_date, qualified
2. For "schedule": fetch upcoming ex-dates from data source
3. For "report": aggregate dividends in date range
4. For "check": return ex-date for symbol if in position
5. Return dividends, total_income, or ex_dates as applicable

## Example
```
Input: action="schedule", symbol="AAPL", start_date="2025-03-01", end_date="2025-06-30"
Output: {
  dividends: [],
  ex_dates: [{symbol: "AAPL", ex_date: "2025-05-09", amount: 0.25}],
  metadata: {action: "schedule", period: "2025-03-01/2025-06-30"}
}
```

## Notes
- Ex-dates from market data or manual entry
- Qualified vs ordinary affects tax treatment
- Integrates with tax-lot-tracker for holding period
