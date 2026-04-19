# Trade Journal Entry

## Purpose
Create structured trade journal entries for post-trade analysis, learning, and compliance.

## Category
utility

## Triggers
- When a trade is closed and post-trade review is needed
- When user requests journaling of recent trades
- When automated trade logging is configured
- When compliance requires trade documentation

## Inputs
- `trade_id`: string — Unique trade identifier
- `symbol`: string — Ticker symbol traded
- `side`: string — "buy" or "sell"
- `quantity`: number — Shares or contracts
- `entry_price`: number — Average entry price
- `exit_price`: number — Average exit price
- `pnl`: number — Realized P&L
- `notes`: string — Optional free-form notes
- `tags`: string[] — Optional tags (e.g., "momentum", "breakout")

## Outputs
- `journal_id`: string — Journal entry identifier
- `entry`: object — Full structured journal record
- `metadata`: object — Timestamp, agent_id, version

## Steps
1. Validate trade_id and required fields
2. Compute derived fields (hold_duration, r_multiple if applicable)
3. Build structured entry with timestamp, P&L, rationale
4. Persist to journal store (DB or file)
5. Return journal_id and confirmation
6. Optionally trigger daily-summary-builder for aggregation

## Example
```
Input: trade_id="T-001", symbol="AAPL", side="buy", quantity=100, entry_price=175.50, exit_price=178.20, pnl=270, notes="Breakout above resistance"
Output: {
  journal_id: "J-20250303-001",
  entry: {trade_id: "T-001", symbol: "AAPL", pnl: 270, hold_duration_hours: 4.5},
  metadata: {created_at: "2025-03-03T16:30:00Z"}
}
```

## Notes
- Journal entries are immutable once created
- Supports both manual and automated trade logging
- Integrates with tax-lot-tracker for cost basis
