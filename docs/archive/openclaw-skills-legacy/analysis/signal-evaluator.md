# Skill: Signal Evaluator

## Purpose
Evaluate trading signals for quality, probability of success, and consistency with risk parameters before execution or forwarding to the execution layer.

## Triggers
- When the agent receives a raw signal and needs to validate it
- When user requests signal quality assessment or filtering
- When building signal pipelines with quality gates
- When backtesting requires signal scoring for strategy optimization

## Inputs
- `signal`: object — Raw signal: symbol, direction, entry, stop, target, source
- `context`: object — Market data, volatility, volume, sentiment (optional)
- `min_quality_score`: number — Minimum score (0-100) to pass (default: 60)
- `risk_params`: object — Max position size, max drawdown, etc.

## Outputs
- `evaluation`: object — quality_score, probability_estimate, pass/fail, reasons
- `adjusted_signal`: object — Signal with suggested adjustments (if any)
- `rejection_reasons`: string[] — Reasons for rejection if failed

## Steps
1. Parse signal: validate symbol, direction (long/short), entry, stop, target
2. Compute risk/reward ratio: (target - entry) / (entry - stop) for longs
3. Check R:R against minimum threshold (e.g., >= 1.5)
4. Fetch or use provided context: ATR, volume, recent price action
5. Score confluence: count supporting factors (technical, sentiment, flow)
6. Assess probability: use historical win rate of similar setups if available
7. Check against risk_params: position size vs account, correlation to existing positions
8. Compute quality_score (0-100): weighted blend of R:R, confluence, probability
9. If quality_score >= min_quality_score, pass; else reject with reasons
10. Return evaluation, adjusted_signal (e.g., tighter stop), and rejection_reasons

## Example
```
Input: signal={symbol: "NVDA", direction: "long", entry: 875, stop: 860, target: 910}, min_quality_score=60
Output: {
  evaluation: {quality_score: 72, probability_estimate: 0.58, pass: true, reasons: ["R:R 2.33", "strong volume"]},
  adjusted_signal: {symbol: "NVDA", direction: "long", entry: 875, stop: 862, target: 910},
  rejection_reasons: []
}
```
