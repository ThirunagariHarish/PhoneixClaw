# Skill: Bracket Order Builder

## Purpose
Build bracket orders (entry + stop-loss + take-profit) for brokers that support OCA (One-Cancels-All) or linked orders, ensuring proper risk management.

## Triggers
- When the agent needs to construct a bracket order from a trade intent
- When user requests bracket order or OCO/OCA setup
- When order-placer receives intent with stop and target
- When building multi-leg orders for defined risk

## Inputs
- `intent`: object — Symbol, side, quantity, entry, stop_loss, take_profit
- `order_type`: string — "market" or "limit" for entry
- `broker`: string — "alpaca", "ibkr" (affects bracket format)
- `tif`: string — "day", "gtc" for child orders

## Outputs
- `orders`: object[] — Array of order objects: entry, stop, target
- `bracket_id`: string — Group ID for linked orders
- `validation`: object — Pass/fail, errors
- `metadata`: object — Broker, bracket_type

## Steps
1. Validate intent: entry, stop, target, quantity; stop and target on correct sides of entry
2. Resolve broker-specific bracket format: Alpaca (bracket order), IBKR (parent + OCA children)
3. Build entry order: market or limit at entry; quantity, side
4. Build stop-loss: stop order at stop price (or stop-market)
5. Build take-profit: limit order at target price
6. Link orders: Alpaca bracket, IBKR OCA group
7. Assign bracket_id for tracking and cancellation
8. Validate: stop and target would not trigger immediately (check current price)
9. Return orders array, bracket_id, validation, metadata
10. Pass to order-placer for submission

## Example
```
Input: intent={symbol: "NVDA", side: "buy", quantity: 50, entry: 875, stop_loss: 860, take_profit: 910}, order_type="limit"
Output: {
  orders: [
    {type: "entry", limit_price: 875, quantity: 50},
    {type: "stop", stop_price: 860, quantity: 50},
    {type: "target", limit_price: 910, quantity: 50}
  ],
  bracket_id: "bracket_xyz789",
  validation: {pass: true, errors: []},
  metadata: {broker: "alpaca", bracket_type: "bracket"}
}
```
