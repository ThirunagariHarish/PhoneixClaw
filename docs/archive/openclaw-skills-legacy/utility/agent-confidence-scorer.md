# Agent Confidence Scorer

## Purpose
Agents report certainty (0-100%) before every trade decision to gate execution and support risk controls.

## Category
utility

## Triggers
- Before submitting any trade order
- When agent proposes entry, exit, or size adjustment
- When user requests confidence metrics for recent decisions
- When integrating with hitl-discord-confirm or other approval gates

## Inputs
- `decision`: object — Proposed action (symbol, side, size, rationale)
- `context`: object — Market state, signals, model outputs used for decision
- `agent_id`: string — Identifier of the agent making the decision
- `min_confidence_threshold`: number — Optional; default 70 (block if below)

## Outputs
- `confidence`: number — 0-100 certainty score
- `confidence_breakdown`: object — Per-factor contributions (signal_strength, regime_clarity, etc.)
- `passes_threshold`: boolean — Whether confidence >= min_confidence_threshold
- `recommendation`: string — PROCEED | HOLD | ABORT based on confidence

## Steps
1. Extract decision type (entry, exit, size_change) and key factors from context
2. Score each factor: signal strength (0-25), regime clarity (0-25), liquidity (0-25), risk/reward (0-25)
3. Aggregate to 0-100; apply penalties for conflicting signals or low volume
4. Compare to min_confidence_threshold; set passes_threshold and recommendation
5. Return confidence, breakdown, passes_threshold, recommendation
6. Log confidence with decision for audit trail

## Example
```
Input: decision={symbol:"AAPL",side:"BUY",size:100,rationale:"breakout"}, context={rsi:65,volume_ratio:1.2},
       min_confidence_threshold=70
Output: {
  confidence: 78,
  confidence_breakdown: {signal_strength: 20, regime_clarity: 22, liquidity: 18, risk_reward: 18},
  passes_threshold: true,
  recommendation: "PROCEED"
}
```

## Notes
- Block execution when recommendation is ABORT or passes_threshold is false
- Calibrate thresholds per strategy; scalping may use higher bar than swing
- Integrate with audit-log-pdf for decision-chain visibility
