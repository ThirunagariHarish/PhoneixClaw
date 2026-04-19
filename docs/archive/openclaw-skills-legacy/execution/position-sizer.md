# Skill: Position Sizer

## Purpose
Calculate position size based on account risk, stop distance, and risk parameters to ensure consistent risk per trade.

## Triggers
- When the agent needs to size a position for a trade
- When user requests position sizing
- When trade-intent-generator needs quantity from signal
- When volatility-adjusted-sizer delegates to base sizing logic

## Inputs
- `account_value`: number — Current account equity
- `risk_per_trade_pct`: number — Max % of account to risk (e.g., 1)
- `entry`: number — Entry price
- `stop`: number — Stop-loss price
- `direction`: string — "long" or "short"
- `symbol`: string — For lot size / share constraints
- `max_position_pct`: number — Optional; max % of account in single position (e.g., 10)

## Outputs
- `quantity`: number — Recommended shares or contracts
- `dollar_risk`: number — Dollar amount at risk
- `dollar_position`: number — Total position value at entry
- `metadata`: object — Risk params used, constraints applied

## Steps
1. Compute risk per share: |entry - stop| for direction
2. Dollar risk = account_value * (risk_per_trade_pct / 100)
3. Quantity = dollar_risk / risk_per_share; round to whole shares
4. Apply max_position_pct: max_value = account_value * (max_position_pct / 100)
5. If quantity * entry > max_value: reduce quantity to max_value / entry
6. Check symbol-specific lot size (e.g., options 100-share multiples)
7. Ensure quantity >= 1 for valid order; else return 0 with reason
8. Compute dollar_risk = quantity * risk_per_share, dollar_position = quantity * entry
9. Return quantity, dollar_risk, dollar_position, metadata
10. Log sizing decision for audit

## Example
```
Input: account_value=100000, risk_per_trade_pct=1, entry=875, stop=860, direction="long"
Output: {
  quantity: 66,
  dollar_risk: 990,
  dollar_position: 57750,
  metadata: {risk_pct: 1, max_position_pct: null}
}
```
