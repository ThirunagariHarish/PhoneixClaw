# Agent Self Optimizer

## Purpose
Self-optimize agent parameters (position size, thresholds) based on performance feedback.

## Category
advanced-ai

## Triggers
- When agent performance degrades
- When scheduled optimization runs
- When user requests parameter tuning
- When reinforcement-reward-calc indicates improvement needed

## Inputs
- `agent_id`: string — Agent to optimize
- `params`: object — Parameters to tune (e.g., position_size, stop_loss_pct)
- `objective`: string — "sharpe", "pnl", "win_rate", "risk_adjusted"
- `method`: string — "grid_search", "bayesian", "genetic"
- `n_trials`: number — Optimization trials (default: 50)
- `constraints`: object — Min/max bounds per param

## Outputs
- `best_params`: object — Optimized parameter values
- `best_score`: number — Objective value at best params
- `history`: object[] — Trial history (param, score)
- `metadata`: object — Agent_id, method, n_trials

## Steps
1. Load agent and current params
2. Define search space from params and constraints
3. Run optimization (grid, Bayesian, genetic)
4. Evaluate each trial via backtest or agent-performance-evaluator
5. Select best params by objective
6. Return best_params, best_score, history
7. Optionally apply best params to agent config

## Example
```
Input: agent_id="agent-001", params={position_size: [0.01, 0.05], stop_loss_pct: [0.02, 0.05]}, objective="sharpe", method="bayesian", n_trials=30
Output: {
  best_params: {position_size: 0.03, stop_loss_pct: 0.03},
  best_score: 1.45,
  history: [...],
  metadata: {agent_id: "agent-001", method: "bayesian", n_trials: 30}
}
```

## Notes
- Bayesian optimization efficient for expensive evaluations
- Constraints prevent invalid params
- Integrates with agent-performance-evaluator for feedback
