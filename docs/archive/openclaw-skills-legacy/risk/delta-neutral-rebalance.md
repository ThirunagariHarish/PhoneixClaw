# Delta-Neutral Rebalance

## Purpose
Rebalance options portfolio to delta-neutral by calculating required hedge adjustments (underlying or options) to achieve zero net delta.

## Category
risk

## Triggers
- When the agent needs to rebalance options portfolio to delta-neutral
- When user requests delta-neutral adjustment or rebalance
- When options delta has drifted from target
- When managing market-neutral options strategies (e.g., straddles, spreads)

## Inputs
- `positions`: object[] — Options positions: symbol, option_id, quantity, delta, underlying
- `underlying_prices`: object — Current underlying prices for hedge calculation
- `target_delta`: number — Target net delta (default: 0)
- `hedge_method`: string — "underlying", "options" (default: underlying)
- `contract_multiplier`: number — Options multiplier (default: 100)

## Outputs
- `net_delta`: number — Current net delta across all positions
- `hedge_quantity`: number — Shares of underlying (or contracts) to trade
- `hedge_side`: string — "buy" or "sell"
- `orders`: object[] — Hedge order specs
- `validation`: object — Pass/fail, delta_after_hedge
- `metadata`: object — Positions_count, computed_at

## Steps
1. Sum deltas across all options positions: net_delta = sum(delta * quantity * multiplier)
2. Compute delta to hedge: net_delta - target_delta
3. If hedge_method=underlying: hedge_quantity = -delta_to_hedge (1 share = 1 delta)
4. Hedge_side: if delta_to_hedge > 0, sell underlying; if < 0, buy underlying
5. Round hedge_quantity to whole shares
6. Build hedge order: symbol=underlying, quantity=abs(hedge_quantity), side=hedge_side
7. Validate: projected delta after hedge near target (within tolerance)
8. Return net_delta, hedge_quantity, hedge_side, orders, validation, metadata
9. Pass to order-placer for execution
10. Optionally use greeks-calculator for fresh delta if positions lack delta

## Example
```
Input: positions=[{symbol: "SPY", option_id: "call_450", quantity: 10, delta: 0.52, underlying: "SPY"}], target_delta=0
Output: {
  net_delta: 520,
  hedge_quantity: -520,
  hedge_side: "sell",
  orders: [{symbol: "SPY", quantity: 520, side: "sell", type: "market"}],
  validation: {pass: true, delta_after_hedge: 0},
  metadata: {positions_count: 1, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Delta changes with price and time; rebalance frequently for active management
- Gamma: delta changes faster near ATM; more frequent rebalance may be needed
- Use underlying for simplicity; options hedge can reduce capital but adds complexity
