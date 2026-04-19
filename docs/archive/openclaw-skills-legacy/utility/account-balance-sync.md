# Account Balance Sync

## Purpose
Sync account balances from brokers to maintain accurate cash and margin visibility.

## Category
utility

## Triggers
- At startup or scheduled intervals
- Before order placement to validate buying power
- When user requests balance refresh
- After large trades or margin changes

## Inputs
- `account_id`: string — Account to sync
- `broker`: string — Broker connector identifier
- `include_positions`: boolean — Also sync position values (default: true)
- `force`: boolean — Force refresh even if recent (default: false)

## Outputs
- `balances`: object — Cash, buying power, equity, margin
- `positions_value`: number — Total positions market value
- `synced_at`: string — Timestamp of sync
- `metadata`: object — Account, broker, status

## Steps
1. Call broker API for account balance
2. Extract cash, buying power, equity, margin
3. Optionally fetch position values and aggregate
4. Persist to system balance store
5. Return balances and synced_at
6. Invalidate cache if force=true

## Example
```
Input: account_id="ACC-001", broker="alpaca", include_positions=true
Output: {
  balances: {cash: 50000, buying_power: 100000, equity: 52500},
  positions_value: 2500,
  synced_at: "2025-03-03T16:45:00Z",
  metadata: {account_id: "ACC-001", broker: "alpaca", status: "ok"}
}
```

## Notes
- Rate limits apply per broker; respect sync frequency
- Buying power may differ from cash (margin)
- Integrates with position-reconciler for consistency
