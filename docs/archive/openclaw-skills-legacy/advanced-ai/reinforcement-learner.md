# Skill: Reinforcement Learner

## Purpose
Apply reinforcement learning (e.g., Q-learning, policy gradient) to optimize trading actions (hold, buy, sell, size) based on reward signals (P&L, Sharpe, drawdown).

## Triggers
- When the agent needs to learn or improve a trading policy
- When user requests RL-based strategy optimization
- When backtest or paper-trading data is available for training
- When exploring adaptive position sizing or entry timing

## Inputs
- `env_type`: string — "discrete", "continuous", or "multi_agent"
- `state_features`: string[] — State representation (e.g., ["price", "position", "pnl"])
- `action_space`: string — "discrete" (hold/buy/sell) or "continuous" (size)
- `reward_fn`: string — "pnl", "sharpe", "risk_adjusted", or "custom"
- `episodes`: number — Training episodes (default: 1000)
- `data_source`: string — "backtest", "paper", or "historical"

## Outputs
- `policy_id`: string — Trained policy identifier
- `metrics`: object — Episode rewards, loss, convergence
- `best_actions`: object — Sample state->action mapping for inspection
- `metadata`: object — Env type, reward fn, trained_at

## Steps
1. Build environment: state from market data, actions from action space
2. Define reward function from P&L, Sharpe, or custom
3. Initialize agent (e.g., DQN, PPO, or simple Q-table)
4. Run episodes: observe state, select action, step env, get reward
5. Update policy via gradient or tabular update
6. Log episode rewards and convergence
7. Persist best policy to registry
8. Return policy_id, metrics, sample best_actions
9. Support checkpoint/resume for long training runs

## Example
```
Input: env_type="discrete", state_features=["rsi","position","pnl_pct"], reward_fn="sharpe", episodes=500
Output: {
  policy_id: "rl_policy_v1",
  metrics: {avg_reward: 0.12, final_episode: 500, converged: true},
  best_actions: {"rsi_30_pos_0": "buy", "rsi_70_pos_1": "sell"},
  metadata: {env_type: "discrete", reward_fn: "sharpe", trained_at: "2025-03-03T15:00:00Z"}
}
```
