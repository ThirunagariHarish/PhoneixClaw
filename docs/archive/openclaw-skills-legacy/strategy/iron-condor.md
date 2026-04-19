# Iron Condor

## Purpose
Construct and manage iron condor options spreads (sell OTM put spread + sell OTM call spread) for defined-risk premium collection in range-bound markets.

## Category
strategy

## Triggers
- When user requests iron condor or premium selling setups
- When IV rank is elevated and underlying expected to stay range-bound
- When agent identifies low-volatility, sideways price action
- When building defined-risk options strategies for earnings or event

## Inputs
- `symbol`: string — Underlying ticker (string)
- `expiration`: string — Option expiration date (string)
- `short_put_delta`: number — Delta of short put, e.g. -0.25 (number)
- `short_call_delta`: number — Delta of short call, e.g. 0.25 (number)
- `width`: number — Width of each spread in strikes (number, default: 5)
- `max_credit`: number — Min credit to accept (number, optional)

## Outputs
- `legs`: object[] — Four legs: short put, long put, short call, long call (object[])
- `credit`: number — Net credit received (number)
- `max_loss`: number — Max loss if breached (number)
- `breakevens`: object — Upper and lower breakeven prices (object)
- `greeks`: object — Net delta, gamma, theta, vega (object)
- `metadata`: object — IV rank, probability OTM (object)

## Steps
1. Fetch underlying price and options chain for expiration
2. Select short put strike at or below short_put_delta (e.g., 25-delta put)
3. Select long put strike width points below short put
4. Select short call strike at or above short_call_delta (e.g., 25-delta call)
5. Select long call strike width points above short call
6. Compute net credit from selling both spreads
7. Calculate max loss = width * 100 - credit (per contract)
8. Compute breakevens: lower = short_put - credit, upper = short_call + credit
9. Aggregate greeks for the 4-leg structure
10. Return legs with strikes, premiums, and risk metrics
11. Optionally compute probability of profit (OTM) from implied distribution

## Example
```
Input: symbol="SPY", expiration="2025-03-21", short_put_delta=-0.25, short_call_delta=0.25, width=5
Output: {
  legs: [{type: "short_put", strike: 570}, {type: "long_put", strike: 565}, {type: "short_call", strike: 585}, {type: "long_call", strike: 590}],
  credit: 1.85,
  max_loss: 3.15,
  breakevens: {lower: 568.15, upper: 586.85},
  greeks: {delta: 0.02, theta: 0.15}
}
```

## Notes
- Best when IV rank 30-70%; avoid low IV (low premium) and extreme high IV (wide ranges)
- Manage at 50% max profit or when short strike breached
- Adjust by rolling untested side or closing entire position
