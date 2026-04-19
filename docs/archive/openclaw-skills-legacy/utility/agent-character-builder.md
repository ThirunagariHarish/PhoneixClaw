# Agent Character Builder

## Purpose
Generate OpenClaw agent config from behavior profile: persona, risk params, strategy preferences, and response style.

## Category
utility

## Triggers
- When creating a new agent from a behavior profile
- When user wants to clone a trader's style into an agent
- When customizing agent after behavior-profiler output
- When loading pre-built character presets

## Inputs
- `behavior_profile`: object — Output from behavior-profiler
- `base_config`: object — Optional: existing agent config to merge/override
- `overrides`: object — User overrides (e.g., max_position_size, risk_tolerance)
- `persona_name`: string — Name for the agent persona (default: "CustomAgent")
- `include_prompt_template`: boolean — Generate system prompt from profile (default: true)

## Outputs
- `agent_config`: object — Full OpenClaw agent config (skills, params, persona)
- `risk_params`: object — position_size_pct, max_drawdown, stop_loss_atr_mult
- `strategy_preferences`: string[] — Preferred strategy skill names
- `system_prompt`: string — Generated system prompt (if include_prompt_template)
- `metadata`: object — profile_confidence, overrides_applied

## Steps
1. Load behavior_profile; validate required fields
2. Map profile.risk_tolerance -> risk_params (conservative: 1% size, 5% DD; aggressive: 3% size, 15% DD)
3. Map profile.holding_period -> strategy_preferences (scalp: momentum-scalp; swing: trend-follower, gap-fill)
4. Map profile.instruments -> enable relevant skills (options-flow for options, etc.)
5. Map profile.entry_style, exit_style -> stop-loss and execution params
6. Apply overrides; merge with base_config if provided
7. Build agent_config: skills list, params, persona (name, description)
8. If include_prompt_template: generate system prompt describing style, risk, preferences
9. Return agent_config, risk_params, strategy_preferences, system_prompt, metadata
10. Validate config against OpenClaw schema before return

## Example
```
Input: behavior_profile={risk_tolerance: "moderate", holding_period: "swing", ...},
       persona_name="SwingTraderJoe", overrides={max_position_size: 2}
Output: {
  agent_config: {persona: {name: "SwingTraderJoe", ...}, skills: ["trend-follower", "gap-fill", ...], params: {...}},
  risk_params: {position_size_pct: 2, max_drawdown: 10, stop_loss_atr_mult: 2},
  strategy_preferences: ["trend-follower", "gap-fill", "opening-range-breakout"],
  system_prompt: "You are SwingTraderJoe, a moderate-risk swing trader...",
  metadata: {profile_confidence: 0.78, overrides_applied: ["max_position_size"]}
}
```

## Notes
- Config format must match OpenClaw agent loader expectations
- Presets can be stored as JSON; load via base_config
- Validate skill names exist in skill registry before including
