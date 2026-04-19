# Multi-Leg Builder

## Purpose
Build multi-leg options orders (spreads, condors, butterflies) from strategy intent and validate legs for execution.

## Category
execution

## Triggers
- When constructing vertical spreads, iron condors, butterflies, or other multi-leg options
- When user specifies strategy type and underlying/strikes
- When converting single-leg intent into multi-leg order for broker
- When validating leg ratios and prices before submission

## Inputs
- `strategy_type`: string — "vertical", "calendar", "iron_condor", "butterfly", "straddle", "strangle"
- `underlying`: string — Symbol (e.g., "SPY", "AAPL")
- `expiration`: string — Expiration date (YYYY-MM-DD)
- `legs`: object[] — [{strike, right, ratio, action}] or auto-generated from strategy_type
- `quantity`: number — Number of spreads/contracts
- `limit_price`: number — Optional: max debit or min credit for spread
- `order_type`: string — "debit", "credit", "market"

## Outputs
- `order_legs`: object[] — Validated legs with strike, right, ratio, quantity, limit_price
- `net_debit_credit`: number — Net cost (negative = credit)
- `max_profit`: number — Max profit if defined (e.g., iron condor)
- `max_loss`: number — Max loss if defined
- `validation_errors`: string[] — Any leg or ratio errors
- `metadata`: object — Strategy_type, greeks_summary

## Steps
1. Parse strategy_type; validate legs or generate from strategy template
2. For vertical: ensure 2 legs, same expiry, opposite sides, 1:1 ratio
3. For iron condor: 4 legs, 2 puts + 2 calls, 1:1:1:1
4. For butterfly: 3 legs, 1:2:1 ratio
5. Validate strikes are valid for underlying and expiration
6. Fetch option chain; resolve contract IDs for each leg
7. Compute net_debit_credit from mid or last; validate vs limit_price
8. Compute max_profit, max_loss for defined strategies
9. Build order_legs array for broker API
10. Return order_legs, net_debit_credit, max_profit, max_loss, validation_errors, metadata

## Example
```
Input: strategy_type="iron_condor", underlying="SPY", expiration="2025-03-21",
       legs=[{strike: 480, right: "put", ratio: -1}, {strike: 475, right: "put", ratio: 1},
             {strike: 520, right: "call", ratio: 1}, {strike: 525, right: "call", ratio: -1}],
       quantity=10
Output: {
  order_legs: [{strike: 480, right: "put", ratio: -1, quantity: 10, contract_id: "..."}, ...],
  net_debit_credit: -1.20,
  max_profit: 1.20,
  max_loss: 3.80,
  validation_errors: [],
  metadata: {strategy_type: "iron_condor", delta: 0.02}
}
```

## Notes
- Broker APIs differ (OCC vs broker-specific); normalize to common format
- Ratio validation critical: e.g., butterfly must be 1:2:1
- Use options-pricing-model or market data for mid prices
