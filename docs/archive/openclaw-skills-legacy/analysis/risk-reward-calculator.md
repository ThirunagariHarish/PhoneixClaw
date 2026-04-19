# Skill: Risk-Reward Calculator

## Purpose
Calculate risk/reward ratio for a trade given entry, stop, and target levels, supporting position sizing and trade quality assessment.

## Triggers
- When the agent needs R:R for a trade idea or signal
- When user requests risk/reward calculation
- When signal-evaluator or position-sizer needs R:R input
- When building trade filters (e.g., only take trades with R:R >= 2)

## Inputs
- `entry`: number — Entry price
- `stop`: number — Stop-loss price
- `target`: number — Take-profit target price
- `direction`: string — "long" or "short"
- `position_size`: number — Optional; shares or contracts for dollar risk
- `account_risk_pct`: number — Optional; max % of account to risk (e.g., 1)

## Outputs
- `risk_reward_ratio`: number — R:R (e.g., 2.0 = 2:1)
- `risk_per_share`: number — Dollar risk per share/contract
- `reward_per_share`: number — Dollar reward per share/contract
- `suggested_size`: number — Shares/contracts for given account_risk_pct
- `metadata`: object — Direction, entry, stop, target

## Steps
1. Validate entry, stop, target: no zeros, sensible ordering
2. For long: risk = entry - stop, reward = target - entry
3. For short: risk = stop - entry, reward = entry - target
4. Ensure risk > 0; if target worse than entry for direction, reward = 0 or flag invalid
5. Compute risk_reward_ratio = reward / risk
6. Compute risk_per_share = |entry - stop|, reward_per_share = |target - entry|
7. If position_size provided: dollar_risk = risk_per_share * position_size
8. If account_risk_pct and account_value provided: suggested_size = (account_value * account_risk_pct/100) / risk_per_share
9. Round suggested_size to whole shares or lot size
10. Return risk_reward_ratio, risk_per_share, reward_per_share, suggested_size, metadata

## Example
```
Input: entry=875, stop=860, target=910, direction="long", account_risk_pct=1, account_value=100000
Output: {
  risk_reward_ratio: 2.33,
  risk_per_share: 15,
  reward_per_share: 35,
  suggested_size: 66,
  metadata: {direction: "long", entry: 875, stop: 860, target: 910}
}
```
