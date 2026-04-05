# Spec: Token Usage Monitor

## Purpose

A dashboard widget showing Claude Code API token usage, costs, and budget tracking. Displayed as a small panel in the sidebar or a dedicated section on the dashboard.

## Widget Design

```
┌─ Claude Code Usage ──────────┐
│ Today:  15,230 tokens  $0.12 │
│ Week:   89,400 tokens  $0.71 │
│ Month: 342,000 tokens  $2.74 │
│ ▓▓▓▓▓▓▓░░░░░ 68% of budget  │
│                              │
│ By Agent:                    │
│ SPX Alerts    3,200  ▓▓▓    │
│ AAPL Swings   2,100  ▓▓     │
│ Backtesting  10,000  ▓▓▓▓▓▓ │
└──────────────────────────────┘
```

## Data Source

Claude Code tracks usage in `~/.claude/` on each VPS. The Agent Gateway periodically collects:

```python
async def collect_token_usage(instance_id):
    conn = await pool.get_connection(instance_id)
    result = await conn.run("cat ~/.claude/usage.json 2>/dev/null || echo '{}'")
    return json.loads(result.stdout)
```

Alternatively, use the Anthropic API usage endpoint if available.

## API

```
GET /api/v2/token-usage
```

Response:
```json
{
  "daily": {
    "input_tokens": 12000,
    "output_tokens": 3230,
    "total_tokens": 15230,
    "estimated_cost_usd": 0.12
  },
  "weekly": {
    "input_tokens": 71000,
    "output_tokens": 18400,
    "total_tokens": 89400,
    "estimated_cost_usd": 0.71
  },
  "monthly": {
    "input_tokens": 270000,
    "output_tokens": 72000,
    "total_tokens": 342000,
    "estimated_cost_usd": 2.74
  },
  "budget": {
    "monthly_limit_usd": 4.00,
    "used_pct": 68.5,
    "remaining_usd": 1.26
  },
  "by_agent": [
    {
      "agent_id": "uuid",
      "agent_name": "SPX Alerts",
      "tokens_today": 3200,
      "cost_today_usd": 0.03
    }
  ],
  "by_model": {
    "claude-haiku": { "tokens": 280000, "cost": 0.07 },
    "claude-sonnet": { "tokens": 62000, "cost": 2.67 }
  }
}
```

## Pricing Model

```python
PRICING = {
    'claude-haiku': {'input_per_1m': 0.25, 'output_per_1m': 1.25},
    'claude-sonnet': {'input_per_1m': 3.00, 'output_per_1m': 15.00},
}
```

## Alerts

- Warning at 80% of monthly budget
- Critical at 95% of monthly budget
- Option to auto-pause non-essential agents at budget limit

## Files to Create

| File | Action |
|------|--------|
| `apps/api/src/routes/token_usage.py` | New |
| `apps/api/src/services/token_tracker.py` | New |
| `apps/dashboard/src/components/TokenMonitor.tsx` | New |
