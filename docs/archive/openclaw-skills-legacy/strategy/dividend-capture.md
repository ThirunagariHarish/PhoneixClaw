# Dividend Capture

## Purpose
Buy stocks before ex-dividend date and sell after to capture dividend income, managing risk around the payment event.

## Category
strategy

## Triggers
- When user requests dividend capture or ex-div plays
- When agent identifies high-yield names with upcoming ex-div dates
- When building income-focused tactical positions
- When validating dividend capture opportunity vs price drop risk

## Inputs
- `symbols`: string[] — Tickers to evaluate (string[])
- `ex_div_date`: string — Target ex-dividend date (string)
- `min_yield`: number — Min annualized yield % (number, optional)
- `max_holding_days`: number — Days to hold around ex-div (number, default: 3)
- `price_stability_filter`: boolean — Require low vol around ex-div (boolean, optional)

## Outputs
- `candidates`: object[] — Symbols with ex-div, yield, and entry/exit dates (object[])
- `expected_income`: number — Total dividend per share (number)
- `risk_metrics`: object — Historical price drop % on ex-div, volatility (object)
- `entry_exit_dates`: object — Buy date, sell date, ex-div date (object)
- `metadata`: object — Dividend amount, yield, payout ratio (object)

## Steps
1. Fetch dividend calendar and ex-div dates for symbols (earnings-calendar or dividend API)
2. Filter to symbols with ex_div_date matching target
3. Get dividend amount and compute yield (annualized)
4. Fetch historical data: price behavior around past ex-div dates
5. Compute avg price drop on ex-div (typically ~dividend amount)
6. Assess risk: if drop > dividend, capture may be negative
7. Define entry: 1-2 days before ex-div; exit: 1 day after (or when price recovers)
8. Apply price_stability_filter: exclude high-vol names if requested
9. Rank by yield and risk-adjusted expected capture
10. Return candidates with entry/exit dates and expected income
11. Include tax consideration note (qualified vs ordinary)

## Example
```
Input: symbols=["T","VZ","PFE"], ex_div_date="2025-03-10", min_yield=4
Output: {
  candidates: [{symbol: "T", dividend: 0.2775, yield: 6.2, entry: "2025-03-07", exit: "2025-03-11"}],
  expected_income: 0.2775,
  risk_metrics: {avg_exdiv_drop: 0.25, volatility: 0.18},
  metadata: {payout_ratio: 0.65}
}
```

## Notes
- Stock typically drops by dividend amount on ex-div; capture works if recovery
- Tax: qualified dividends taxed lower; holding period matters for qualification
- Avoid in taxable accounts if short-term; consider wash sale rules
