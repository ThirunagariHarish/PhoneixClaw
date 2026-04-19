# Wheel Strategy

## Purpose
Execute the options wheel: sell cash-secured put, get assigned, then sell covered call; repeat for income and potential stock acquisition.

## Category
strategy

## Triggers
- When user requests wheel strategy or premium income on desired stocks
- When agent identifies quality names user wants to own at lower price
- When building systematic put-selling or covered-call income
- When managing assigned positions from previous put sales

## Inputs
- `symbol`: string — Ticker to wheel (string)
- `phase`: string — "put_sell", "assigned", "call_sell" (string)
- `target_premium`: number — Min premium per contract (number, optional)
- `strike_selection`: string — "atm", "otm_5", "otm_10", or delta (string)
- `expiration`: string — Option expiration (string)
- `cost_basis`: number — Assignment cost if phase is assigned (number, optional)

## Outputs
- `action`: string — "sell_put", "sell_call", "hold", "roll" (string)
- `strike`: number — Recommended strike (number)
- `premium`: number — Expected credit (number)
- `position_legs`: object[] — Order legs to place (object[])
- `next_phase`: string — Expected next phase after execution (string)
- `metadata`: object — IV rank, days to expiration, assignment probability (object)

## Steps
1. If phase is "put_sell": fetch underlying price and put chain
2. Select strike: ATM or OTM based on strike_selection; target 30-45 DTE
3. Validate premium >= target_premium; filter by delta (e.g., 0.30 put)
4. Return sell_put order with strike and premium
5. If phase is "assigned": user holds stock; transition to "call_sell"
6. If phase is "call_sell": use cost_basis as reference; sell call above cost
7. Select call strike above cost_basis (e.g., 1-2% OTM) for covered call
8. Return sell_call order; on assignment, stock sold; restart wheel with put_sell
9. Handle roll: if put tested, roll down/out for credit when possible
10. Return action, strike, premium, and next phase

## Example
```
Input: symbol="AAPL", phase="put_sell", strike_selection="otm_5", expiration="2025-04-18"
Output: {
  action: "sell_put",
  strike: 170,
  premium: 2.40,
  position_legs: [{side: "sell", type: "put", strike: 170, qty: 1}],
  next_phase: "put_sell",
  metadata: {dte: 45, iv_rank: 42}
}
```

## Notes
- Only wheel stocks you are willing to hold long-term
- Assignment creates concentrated position; size accordingly
- Roll puts before deep ITM to avoid assignment if undesired
