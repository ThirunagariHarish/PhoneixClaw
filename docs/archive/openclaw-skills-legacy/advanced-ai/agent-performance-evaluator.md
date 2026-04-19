# Agent Performance Evaluator

## Purpose
Evaluate agent performance metrics (win rate, Sharpe, drawdown) for tuning and comparison.

## Category
advanced-ai

## Triggers
- After agent trading episode or period
- When comparing agent versions
- When user requests agent evaluation
- When agent-self-optimizer needs metrics

## Inputs
- `agent_id`: string — Agent identifier
- `trades`: object[] — Trades executed by agent
- `period`: object — Start/end dates
- `benchmark`: string — Optional benchmark for comparison
- `metrics`: string[] — Metrics to compute (default: all)

## Outputs
- `metrics`: object — Win rate, Sharpe, max DD, profit factor, etc.
- `rank`: number — Relative rank vs other agents (if applicable)
- `recommendations`: string[] — Suggested improvements
- `metadata`: object — Agent_id, period, benchmark

## Steps
1. Load trades for agent and period
2. Compute P&L series and statistics
3. Calculate requested metrics (Sharpe, Sortino, max DD)
4. Compare to benchmark if provided
5. Generate recommendations from weak areas
6. Return metrics, rank, recommendations

## Example
```
Input: agent_id="agent-001", trades=[...], period={start: "2025-02-01", end: "2025-02-28"}, metrics=["sharpe","win_rate","max_dd"]
Output: {
  metrics: {sharpe: 1.2, win_rate: 0.58, max_dd: -0.06},
  rank: 3,
  recommendations: ["Reduce position size in drawdown periods"],
  metadata: {agent_id: "agent-001", period: "2025-02-01/2025-02-28"}
}
```

## Notes
- Requires sufficient trades for statistical significance
- Benchmark comparison uses excess return
- Integrates with agent-self-optimizer for feedback loop
