# Reinforcement Reward Calc

## Purpose
Calculate RL reward signals from trade outcomes for reinforcement learning agents.

## Category
advanced-ai

## Triggers
- When training RL trading agents
- When computing reward for completed episode
- When user requests reward calculation
- When reinforcement-learner needs reward signal

## Inputs
- `trades`: object[] — List of trades with P&L, hold time
- `episode_pnl`: number — Total episode P&L
- `reward_type`: string — "pnl", "sharpe", "risk_adjusted", "custom"
- `risk_free_rate`: number — For Sharpe-style rewards (default: 0)
- `penalty_config`: object — Penalties for drawdown, turnover, etc.

## Outputs
- `reward`: number — Scalar reward for episode
- `components`: object — Breakdown (pnl_component, penalty_component)
- `metadata`: object — Reward type, config, episode_id
- `per_trade_rewards`: number[] — Reward per trade (optional)

## Steps
1. Aggregate trade outcomes (P&L, count, hold times)
2. Compute base reward per reward_type (raw P&L, Sharpe, etc.)
3. Apply penalties (drawdown, excessive turnover)
4. Normalize or scale if configured
5. Return reward and component breakdown
6. Optionally compute per-trade rewards for credit assignment

## Example
```
Input: trades=[...], episode_pnl=500, reward_type="risk_adjusted", penalty_config={drawdown_penalty: 0.1}
Output: {
  reward: 0.42,
  components: {pnl_component: 0.5, drawdown_penalty: -0.08},
  metadata: {reward_type: "risk_adjusted", episode_id: "ep-001"}
}
```

## Notes
- Sparse vs dense reward configurable
- Penalties discourage undesirable behavior
- Integrates with reinforcement-learner
