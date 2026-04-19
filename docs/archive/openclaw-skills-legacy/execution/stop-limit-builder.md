# Stop-Limit Order Builder

## Purpose
Build stop-limit orders with calculated stop and limit levels based on ATR, support/resistance, or percentage rules for precise execution control.

## Category
execution

## Triggers
- When the agent needs stop-limit orders with calculated levels
- When user requests stop-limit or stop with limit
- When building orders that trigger at stop but execute at limit
- When combining volatility-based stops with limit price caps

## Inputs
- `symbol`: string — Ticker
- `side`: string — "buy" or "sell"
- `quantity`: number — Shares or contracts
- `stop_method`: string — "atr", "percent", "price", "support_resistance"
- `stop_value`: number — ATR multiplier, percent, or absolute price
- `limit_offset`: number — Limit offset from stop (e.g., 0.5% or $0.10)
- `current_price`: number — Current market price for validation
- `atr`: number — Optional ATR if stop_method="atr"
- `reference_price`: number — Optional support/resistance level

## Outputs
- `stop_price`: number — Calculated stop trigger price
- `limit_price`: number — Calculated limit execution price
- `order`: object — Full stop-limit order spec
- `validation`: object — Pass/fail, warnings (e.g., limit too far)
- `metadata`: object — Method used, inputs, computed_at

## Steps
1. Validate inputs: symbol, side, quantity, current_price
2. Compute stop_price: if atr → current ± (atr * stop_value); if percent → current ± (current * stop_value/100); if price → stop_value; if support_resistance → reference_price
3. Compute limit_price: stop_price ± limit_offset (buy: limit above stop; sell: limit below stop)
4. Validate: stop and limit on correct side of current price; limit not excessively far from stop
5. Build order object: symbol, side, quantity, stop_price, limit_price, order_type="stop_limit"
6. Return stop_price, limit_price, order, validation, metadata
7. Pass to order-placer for submission
8. Optionally use trailing-stop logic for dynamic stop updates

## Example
```
Input: symbol="AAPL", side="sell", quantity=100, stop_method="atr", stop_value=2, limit_offset=0.003, current_price=175, atr=2.5
Output: {
  stop_price: 170,
  limit_price: 169.49,
  order: {symbol: "AAPL", side: "sell", quantity: 100, stop_price: 170, limit_price: 169.49, order_type: "stop_limit"},
  validation: {pass: true, warnings: []},
  metadata: {method: "atr", atr_mult: 2, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Stop-limit may not fill in fast markets if price gaps through limit
- Use limit_offset to allow slippage; too tight may result in no fill
- ATR-based stops adapt to volatility; percent is simpler but static
