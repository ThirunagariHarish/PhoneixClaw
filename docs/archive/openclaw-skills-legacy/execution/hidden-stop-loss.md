# Hidden Stop Loss

## Purpose
Server-side stop orders held locally, not visible on broker order books, to avoid front-running and information leakage.

## Category
execution

## Triggers
- When user wants stop-loss protection without exposing level to market
- When trading illiquid names where visible stops get hunted
- When strategy requires stealth execution of risk management

## Inputs
- `symbol`: string — Ticker symbol
- `side`: string — "buy" or "sell"
- `quantity`: number — Shares or contracts
- `stop_price`: number — Price that triggers market order
- `order_type`: string — "stop_market" or "stop_limit" (default: stop_market)
- `limit_price`: number — Optional: for stop_limit, price after trigger
- `position_id`: string — Optional: link to position for tracking

## Outputs
- `hidden_stop_id`: string — Internal ID for this hidden stop
- `status`: string — "active", "triggered", "cancelled"
- `triggered_at`: string — ISO timestamp when stop fired (if applicable)
- `fill_price`: number — Execution price (if triggered)
- `metadata`: object — symbol, stop_price, created_at

## Steps
1. Validate stop_price vs current market (e.g., stop below bid for sell)
2. Store hidden stop in local state/DB with unique ID
3. Subscribe to real-time price feed for symbol
4. On each tick: compare price to stop_price; if breached, submit market (or limit) order
5. On fill: update status, record fill_price, remove from active list
6. Expose cancel endpoint; user can cancel hidden stop before trigger
7. Return hidden_stop_id, status; poll or WebSocket for triggered/fill updates

## Example
```
Input: symbol="AAPL", side="sell", quantity=100, stop_price=175.50, order_type="stop_market"
Output: {
  hidden_stop_id: "hstop_abc123",
  status: "active",
  metadata: {symbol: "AAPL", stop_price: 175.50, created_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Requires persistent process; stops lost if server restarts without persistence
- Latency: local tick processing adds delay vs broker-native stops
- Consider hybrid: broker stop for critical levels, hidden for discretionary
