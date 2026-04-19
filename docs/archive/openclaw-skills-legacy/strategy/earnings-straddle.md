# Earnings Straddle

## Purpose
Set up long straddle or strangle positions before earnings to profit from large post-announcement moves regardless of direction.

## Category
strategy

## Triggers
- When user requests earnings play or volatility expansion trade
- When earnings date is within 1-7 days and IV is relatively low
- When agent identifies high-move-potential names (historical earnings vol)
- When building event-driven options strategies

## Inputs
- `symbol`: string — Ticker with upcoming earnings (string)
- `strategy_type`: string — "straddle" or "strangle" (string)
- `expiration`: string — First expiration after earnings (string)
- `strangle_width`: number — OTM width for strangle (number, e.g. 0.02 = 2% OTM)
- `max_premium`: number — Max debit to pay (number, optional)
- `earnings_date`: string — Expected earnings date (string, optional)

## Outputs
- `legs`: object[] — Put and call legs (strike, premium each) (object[])
- `total_debit`: number — Net cost of position (number)
- `breakevens`: object — Upper and lower breakeven prices (object)
- `implied_move`: number — Market-implied move from options (number)
- `historical_move`: number — Avg historical earnings move % (number)
- `metadata`: object — IV rank, earnings date, days to expiry (object)

## Steps
1. Fetch earnings date from earnings-calendar or market-calendar-checker
2. Fetch underlying price and options chain for expiration (post-earnings)
3. For straddle: buy ATM put and ATM call, same strike
4. For strangle: buy OTM put and OTM call, strikes at strangle_width from spot
5. Compute total debit (put premium + call premium)
6. Calculate breakevens: lower = strike - debit, upper = strike + debit (straddle)
7. Derive implied move from ATM straddle price (or strangle)
8. Fetch historical earnings move % from past 4-8 quarters
9. Compare implied vs historical: if implied < historical, potential edge
10. Return legs, debit, breakevens, implied/historical move
11. Validate total_debit <= max_premium if provided

## Example
```
Input: symbol="NVDA", strategy_type="straddle", expiration="2025-03-21"
Output: {
  legs: [{type: "put", strike: 875, premium: 18.50}, {type: "call", strike: 875, premium: 20.20}],
  total_debit: 38.70,
  breakevens: {lower: 836.30, upper: 913.70},
  implied_move: 4.4,
  historical_move: 6.2,
  metadata: {earnings_date: "2025-03-19", iv_rank: 35}
}
```

## Notes
- IV crush after earnings can hurt long premium; buy close to event
- Strangle cheaper but needs larger move; straddle more sensitive to IV
- Consider selling further-dated options to reduce theta decay pre-earnings
