# Position Reconciler

## Purpose
Reconcile positions between broker and system to detect and resolve discrepancies.

## Category
utility

## Triggers
- At scheduled reconciliation intervals
- When user requests position reconciliation
- After bulk trade imports or migrations
- When position mismatch alerts fire

## Inputs
- `account_id`: string — Account to reconcile
- `broker`: string — Broker connector (e.g., "alpaca", "ibkr")
- `tolerance`: number — Qty tolerance for rounding (default: 0)
- `symbols`: string[] — Specific symbols to check (optional; default: all)

## Outputs
- `matches`: object[] — Positions that match
- `discrepancies`: object[] — Positions with differences
- `summary`: object — Count of matches, discrepancies, resolved
- `actions_taken`: string[] — Auto-resolutions if any

## Steps
1. Fetch positions from broker API
2. Fetch positions from system (DB/cache)
3. Match by symbol; compare quantity and cost basis
4. Flag discrepancies beyond tolerance
5. Optionally auto-resolve (trust broker, trust system, or manual)
6. Log reconciliation result for audit
7. Return matches, discrepancies, summary

## Example
```
Input: account_id="ACC-001", broker="alpaca", tolerance=0.001
Output: {
  matches: [{symbol: "AAPL", qty: 100, broker_qty: 100}],
  discrepancies: [{symbol: "NVDA", system_qty: 50, broker_qty: 48, diff: 2}],
  summary: {matches: 12, discrepancies: 1},
  actions_taken: []
}
```

## Notes
- Tolerance handles fractional share rounding
- Cost basis may differ; focus on quantity first
- Triggers alert-composer for critical discrepancies
