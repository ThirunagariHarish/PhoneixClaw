# LLM Cost Tracker

## Purpose
Monitor API token usage costs per decision and per agent for budget control and optimization.

## Category
utility

## Triggers
- After each LLM API call (completion, embedding)
- When user requests cost summary (daily, per-agent, per-skill)
- When cost exceeds budget threshold or anomaly detected
- When evaluating multi-model-fallback or model selection

## Inputs
- `provider`: string — "openai", "anthropic", "local", etc.
- `model`: string — Model name (e.g., gpt-4o, claude-3-opus)
- `input_tokens`: number — Tokens in prompt
- `output_tokens`: number — Tokens in response
- `agent_id`: string — Optional; agent making the call
- `skill_name`: string — Optional; skill invoking the call
- `decision_id`: string — Optional; link to trade decision

## Outputs
- `cost_usd`: number — Estimated cost in USD
- `cumulative_daily`: number — Running daily total
- `by_agent`: object — Per-agent cost breakdown
- `by_skill`: object — Per-skill cost breakdown
- `alert`: boolean — True if over budget or anomaly

## Steps
1. Look up provider/model pricing (input $/1K, output $/1K)
2. Compute cost_usd = (input_tokens * input_rate + output_tokens * output_rate) / 1000
3. Append to time-series store; aggregate by day, agent, skill
4. Check against daily budget; set alert if exceeded or spike
5. Return cost_usd, cumulative_daily, by_agent, by_skill, alert
6. Optionally emit metric to monitoring (Prometheus, etc.)

## Example
```
Input: provider="openai", model="gpt-4o", input_tokens=2500, output_tokens=400, agent_id="daily-signals"
Output: {
  cost_usd: 0.0185,
  cumulative_daily: 2.34,
  by_agent: {daily_signals: 1.2, risk_analyzer: 0.8},
  by_skill: {trend_follower: 0.9, gap_fill: 0.5},
  alert: false
}
```

## Notes
- Pricing tables must be updated when providers change rates
- Local models report 0 cost; track GPU time separately if needed
- Use with multi-model-fallback to prefer cheaper models when appropriate
