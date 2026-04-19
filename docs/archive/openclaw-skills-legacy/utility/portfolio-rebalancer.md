# Skill: Portfolio Rebalancer

## Purpose
Compute target allocations and rebalance orders to bring portfolio weights back to target (e.g., equal-weight, sector targets, risk-parity).

## Triggers
- When the agent needs to rebalance a portfolio
- When user requests rebalancing to target weights
- When scheduled rebalance (e.g., monthly) is due
- When drift exceeds threshold from target allocation

## Inputs
- `positions`: object[] — Current positions: symbol, qty, market_value
- `target_weights`: object — Target weight per symbol (e.g., {AAPL: 0.2, NVDA: 0.3})
- `total_value`: number — Portfolio value (or sum of positions)
- `min_trade_value`: number — Minimum trade size in $ to execute (default: 100)
- `dry_run`: boolean — If true, return orders without submitting (default: false)

## Outputs
- `orders`: object[] — Rebalance orders: symbol, side, qty, reason
- `drift`: object — Per-symbol weight drift before rebalance
- `new_weights`: object — Target weights after rebalance
- `metadata`: object — Total value, order count, dry_run

## Steps
1. Compute current weights: position_value / total_value per symbol
2. Compute drift: current_weight - target_weight
3. Determine target dollar amount per symbol: total_value * target_weight
4. Compute delta: target_dollars - current_value
5. Convert delta to shares (round to lot size if applicable)
6. Filter orders below min_trade_value
7. Sort by absolute delta (largest first) for execution priority
8. If dry_run: return orders only; else submit via order-placer
9. Return orders, drift, new_weights, metadata

## Example
```
Input: positions=[{symbol: "AAPL", market_value: 20000}, {symbol: "NVDA", market_value: 35000}], target_weights={AAPL: 0.4, NVDA: 0.6}, total_value=55000
Output: {
  orders: [{symbol: "AAPL", side: "buy", qty: 5, reason: "rebalance"}, {symbol: "NVDA", side: "sell", qty: 3, reason: "rebalance"}],
  drift: {AAPL: -0.036, NVDA: 0.036},
  new_weights: {AAPL: 0.4, NVDA: 0.6},
  metadata: {total_value: 55000, order_count: 2, dry_run: false}
}
```
