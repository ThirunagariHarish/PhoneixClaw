# Calendar Spread

## Purpose
Construct options calendar (time) spreads: sell near-term option, buy longer-dated option at same strike to profit from time decay and IV differential.

## Category
strategy

## Triggers
- When user requests calendar spread or time spread strategy
- When near-term IV is elevated vs back-month (positive IV skew)
- When agent expects range-bound price action through near expiry
- When building theta-positive, vega-neutral options positions

## Inputs
- `symbol`: string — Underlying ticker (string)
- `strike`: number — Strike price (same for both legs) (number)
- `short_expiration`: string — Near-term expiration to sell (string)
- `long_expiration`: string — Back-month expiration to buy (string)
- `option_type`: string — "call" or "put" (string)
- `max_debit`: number — Max net debit to pay (number, optional)

## Outputs
- `legs`: object[] — Short and long legs (strike, expiration, premium) (object[])
- `net_debit`: number — Cost to open spread (number)
- `max_profit`: number — Theoretical max if short expires worthless (number)
- `breakeven`: number — Price at max profit scenario (number)
- `greeks`: object — Net delta, theta, vega (object)
- `metadata`: object — IV term structure, DTE each leg (object)

## Steps
1. Fetch underlying price and options chain for both expirations
2. Select strike (typically ATM or slight OTM)
3. Sell 1 contract of short_expiration at strike (call or put)
4. Buy 1 contract of long_expiration at same strike
5. Compute net_debit = long_premium - short_premium (usually debit)
6. Max profit: short premium received if short expires worthless
7. Breakeven: complex; depends on decay and price path
8. Aggregate greeks: calendar is long theta (benefits from time decay of short)
9. Vega: typically long vega (long-dated more sensitive)
10. Return legs, net_debit, max_profit, greeks
11. Validate net_debit <= max_debit if provided
12. Check IV term structure: prefer short IV > long IV for credit benefit

## Example
```
Input: symbol="SPY", strike=575, short_expiration="2025-03-21", long_expiration="2025-04-18", option_type="call"
Output: {
  legs: [{side: "sell", expiration: "2025-03-21", premium: 3.20}, {side: "buy", expiration: "2025-04-18", premium: 5.80}],
  net_debit: 2.60,
  max_profit: 3.20,
  greeks: {theta: 0.08, vega: 0.12, delta: 0.05},
  metadata: {short_dte: 18, long_dte: 45}
}
```

## Notes
- Best when near-term IV elevated (earnings, event) vs back-month
- Risk: large move through short expiry can cause loss
- Manage: close before short expiry if profitable or if underlying moves against
