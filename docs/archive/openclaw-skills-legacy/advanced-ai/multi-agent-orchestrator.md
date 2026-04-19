# Skill: Multi-Agent Orchestrator

## Purpose
Coordinate multiple specialized agents (e.g., research, execution, risk) to accomplish complex tasks by delegating subtasks and aggregating results.

## Triggers
- When the agent needs to split a complex task across specialists
- When user requests multi-step workflows (research -> signal -> execute)
- When parallel analysis from different agent types is needed
- When handoff between research and execution agents is required

## Inputs
- `task`: string — High-level task description
- `agents`: string[] — Agent roles to involve (e.g., ["research", "risk", "execution"])
- `workflow`: string — "sequential", "parallel", or "dag" — execution pattern
- `context`: object — Shared context (symbols, constraints, prior results)
- `timeout_sec`: number — Max time for orchestration (default: 60)

## Outputs
- `results`: object — Per-agent outputs keyed by agent name
- `summary`: string — Aggregated summary or final answer
- `status`: string — "completed", "partial", "failed"
- `metadata`: object — Agents used, workflow, duration_ms

## Steps
1. Parse task; identify subtasks per agent capability
2. Resolve agent instances from registry (research, risk, execution, etc.)
3. For sequential: run research -> risk -> execution in order; pass context
4. For parallel: invoke research and risk simultaneously; merge results
5. For dag: resolve dependency graph; execute in topological order
6. Collect outputs; handle timeouts and failures gracefully
7. Aggregate results; optionally synthesize summary via LLM
8. Return results, summary, status
9. Log orchestration for debugging and analytics

## Example
```
Input: task="Research NVDA, check risk, then place buy order if approved", agents=["research","risk","execution"], workflow="sequential"
Output: {
  results: {research: {signal: "buy", confidence: 0.8}, risk: {approved: true}, execution: {order_id: "ord_123"}},
  summary: "Research signaled buy with 0.8 confidence; risk approved; order ord_123 placed.",
  status: "completed",
  metadata: {agents: ["research","risk","execution"], workflow: "sequential", duration_ms: 3200}
}
```
