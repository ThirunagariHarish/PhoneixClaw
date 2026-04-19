# Tax Lot Tracker

## Purpose
Track tax lots for gain/loss reporting and support FIFO, LIFO, or specific identification.

## Category
utility

## Triggers
- When a buy order fills and lot needs recording
- When a sell order fills and cost basis must be assigned
- When user requests tax lot report
- When generating year-end gain/loss summary

## Inputs
- `action`: string — "add", "reduce", "report", "assign"
- `symbol`: string — Ticker symbol
- `quantity`: number — Shares/contracts
- `price`: number — Price per share
- `trade_date`: string — Trade date (ISO)
- `lot_id`: string — Specific lot for "assign" (optional)
- `method`: string — "FIFO", "LIFO", or "specific"

## Outputs
- `lots`: object[] — Current or remaining lots
- `realized_gain`: number — Realized gain/loss from reduce
- `report`: object — Tax lot report when action=report
- `metadata`: object — Lot IDs, method, timestamps

## Steps
1. For "add": create new lot with quantity, price, trade_date
2. For "reduce": select lots per method (FIFO/LIFO/specific)
3. Compute realized gain/loss from cost basis vs sale price
4. Update or remove lots accordingly
5. For "report": aggregate all lots and unrealized P&L
6. Return lots, realized_gain, or report

## Example
```
Input: action="reduce", symbol="AAPL", quantity=50, price=180, method="FIFO"
Output: {
  lots: [{quantity: 50, cost_basis: 175, remaining: 50}],
  realized_gain: 250,
  metadata: {method: "FIFO", lots_reduced: 1}
}
```

## Notes
- Maintains lot-level detail for audit trail
- Supports wash sale adjustment if configured
- Integrates with dividend-tracker for qualified dividends
