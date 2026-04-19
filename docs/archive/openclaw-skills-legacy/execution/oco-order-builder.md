# OCO Order Builder

## Purpose
Build one-cancels-other (OCO) order pairs where execution of one order automatically cancels the other, useful for bracketed exits and breakout/breakdown entries.

## Category
execution

## Triggers
- When the agent needs to construct OCO order pairs
- When user requests OCO or one-cancels-other setup
- When building dual-sided exit orders (take-profit vs stop-loss)
- When placing breakout orders above resistance and below support

## Inputs
- `symbol`: string — Ticker
- `side`: string — "buy" or "sell"
- `quantity`: number — Shares or contracts per order
- `order_a`: object — First order: {type, price, order_type} (e.g., limit at 910)
- `order_b`: object — Second order: {type, price, order_type} (e.g., stop at 860)
- `broker`: string — "alpaca", "ibkr" (affects OCO format)
- `tif`: string — "day", "gtc" for time-in-force

## Outputs
- `orders`: object[] — Array of two linked orders
- `oco_group_id`: string — Group ID for OCO linkage
- `validation`: object — Pass/fail, errors
- `metadata`: object — Broker, oco_type

## Steps
1. Validate both orders: prices, quantity, side
2. Ensure orders are mutually exclusive (e.g., one limit above market, one stop below)
3. Resolve broker-specific OCO format: Alpaca (OCO group), IBKR (OCA group)
4. Build order A: limit or stop-limit at specified price
5. Build order B: limit or stop at specified price
6. Link orders with OCO/OCA group ID
7. Validate: neither order would fill immediately at current price
8. Return orders array, oco_group_id, validation, metadata
9. Pass to order-placer for submission
10. Track OCO group for cancellation if needed

## Example
```
Input: symbol="NVDA", side="buy", quantity=50, order_a={type: "limit", price: 910}, order_b={type: "stop", price: 860}, broker="alpaca"
Output: {
  orders: [
    {type: "limit", limit_price: 910, quantity: 50, side: "buy"},
    {type: "stop", stop_price: 860, quantity: 50, side: "buy"}
  ],
  oco_group_id: "oco_abc123",
  validation: {pass: true, errors: []},
  metadata: {broker: "alpaca", oco_type: "oco"}
}
```

## Notes
- Both orders must be same symbol, side, quantity
- OCO typically used for exits (one target, one stop) or breakout entries
- Broker support varies; IBKR uses OCA (One-Cancels-All) for multi-order groups
