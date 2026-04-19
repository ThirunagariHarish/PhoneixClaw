# Skill: Stop-Loss Manager

## Purpose
Manage stop-loss levels for open positions: set, adjust, and monitor stops to limit downside while allowing profitable trades to run.

## Triggers
- When the agent needs to set or update stop-loss for a position
- When user requests stop management or stop adjustment
- When new positions are opened and require initial stops
- When trailing-stop-calculator output needs to be applied

## Inputs
- `position`: object — Symbol, side, quantity, entry_price, current_stop
- `stop_level`: number — New stop price to set
- `action`: string — "set", "update", "cancel", or "check"
- `reason`: string — Optional: "initial", "trailing", "breakeven", "manual"
- `broker`: string — Broker for order placement

## Outputs
- `result`: object — success, order_id (if placed), previous_stop
- `validation`: object — stop_valid (price check), errors
- `metadata`: object — Action, timestamp, reason

## Steps
1. Validate position: symbol, quantity, entry, current_stop
2. For "set" or "update": validate stop_level vs entry and side
3. Long: stop must be below entry and current price; short: stop above entry
4. Check stop distance: ensure not too tight (e.g., min 0.5% from entry)
5. Resolve broker: fetch existing stop order if any; cancel if updating
6. Place new stop order: stop-market or stop-limit at stop_level
7. Update position record with new stop; log reason
8. For "cancel": cancel existing stop order; clear stop from position
9. For "check": validate current stop still appropriate; return validation
10. Return result, validation, metadata

## Example
```
Input: position={symbol: "NVDA", side: "long", quantity: 50, entry_price: 875, current_stop: 860}, action="update", stop_level=868, reason="trailing"
Output: {
  result: {success: true, order_id: "ord_stop_123", previous_stop: 860},
  validation: {stop_valid: true, errors: []},
  metadata: {action: "update", timestamp: "2025-03-03T15:00:00Z", reason: "trailing"}
}
```
