# Behavior Profiler

## Purpose
Build a trading behavior profile from transcripts, messages, and trade history to capture style, risk tolerance, and preferences.

## Category
utility

## Triggers
- When user provides transcripts or messages for profile extraction
- When configuring agent to mimic a specific trader's style
- When building agent-character from historical behavior
- When analyzing consistency of trading decisions over time

## Inputs
- `sources`: object[] — [{type: "transcript"|"discord"|"trades", content: string|object[]}]
- `min_samples`: number — Minimum samples for reliable profile (default: 10)
- `include_trade_history`: boolean — Use actual trade data if available (default: true)
- `output_format`: string — "profile", "traits", "full" (default: "profile")

## Outputs
- `profile`: object — {risk_tolerance, holding_period, sectors, instruments, entry_style, exit_style}
- `traits`: object[] — Extracted traits with confidence scores
- `sample_quotes`: string[] — Representative quotes supporting traits
- `confidence`: number — Overall profile confidence (0–1)
- `metadata`: object — sources_used, sample_count, model_used

## Steps
1. Aggregate content from all sources (transcripts, Discord, trade logs)
2. Extract text; chunk if large; run through LLM or NLP for trait extraction
3. Identify: risk_tolerance (conservative/moderate/aggressive), holding_period (scalp/swing/long)
4. Identify: preferred sectors, instruments (stocks/options/crypto), entry/exit style
5. Extract sample_quotes that support each trait
6. If trade_history: compute actual stats (avg hold, win rate, size) to validate
7. Compute confidence from sample count and consistency of signals
8. Return profile, traits, sample_quotes, confidence, metadata
9. Format for agent-character-builder consumption
10. Cache profile by source hash for incremental updates

## Example
```
Input: sources=[{type: "transcript", content: "..."}, {type: "discord", content: [...]}]
Output: {
  profile: {
    risk_tolerance: "moderate",
    holding_period: "swing",
    sectors: ["tech", "growth"],
    instruments: ["stocks", "options"],
    entry_style: "pullback",
    exit_style: "trailing_stop"
  },
  traits: [{trait: "patient", confidence: 0.85}, {trait: "momentum", confidence: 0.72}],
  sample_quotes: ["I like to buy the dip on strength", "Trailing stop at 2 ATR"],
  confidence: 0.78,
  metadata: {sources_used: 2, sample_count: 45}
}
```

## Notes
- LLM extraction works well; use structured output (JSON) for reliability
- Trade history is ground truth; weight higher than self-reported style
- Profile can drive position-sizer, stop-loss-manager, and strategy selection
