# Skill: Trade Intent Generator

## Purpose
Generate structured trade intents from raw signals, analysis outputs, and user instructions for downstream execution and risk checks.

## Triggers
- When the agent has a signal or idea and needs a formal trade intent
- When user requests trade intent generation from analysis
- When bridging signal-evaluator output to execution pipeline
- When converting natural language trade ideas to structured format

## Inputs
- `signal`: object — Raw signal: symbol, direction, entry, stop, target, source
- `analysis`: object — Optional: technical, sentiment, flow analysis outputs
- `constraints`: object — Optional: max size, session filter, symbol whitelist
- `intent_type`: string — "market", "limit", "bracket", or "scale_in"

## Outputs
- `intent`: object — Structured intent: symbol, side, quantity, order_type, stop, target, tif
- `validation`: object — Pass/fail, validation_errors
- `metadata`: object — Generated_at, source_signal_id

## Steps
1. Parse signal: extract symbol, direction (buy/sell), entry, stop, target
2. Resolve quantity: use position-sizer if size not provided; apply constraints
3. Set order_type: market (immediate), limit (at entry), or bracket (entry + stop + target)
4. Map time-in-force: day, gtc, ioc, fok based on intent_type
5. Validate: symbol format, positive quantity, stop/target vs entry for direction
6. Apply constraints: max size, symbol whitelist, session (use time-of-day-filter)
7. Build intent object with all required fields for execution queue
8. Run validation; return validation_errors if any
9. Return intent, validation, metadata
10. Log intent for audit trail

## Example
```
Input: signal={symbol: "NVDA", direction: "long", entry: 875, stop: 860, target: 910}, constraints={max_size: 100}
Output: {
  intent: {symbol: "NVDA", side: "buy", quantity: 50, order_type: "limit", limit_price: 875, stop_loss: 860, take_profit: 910, tif: "day"},
  validation: {pass: true, errors: []},
  metadata: {generated_at: "2025-03-03T15:00:00Z", source: "signal_evaluator"}
}
```
