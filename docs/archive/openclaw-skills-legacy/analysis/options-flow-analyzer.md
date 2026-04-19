# Skill: Options Flow Analyzer

## Purpose
Analyze unusual options flow to derive directional bias (bullish/bearish), key strike levels, and conviction strength for trading and risk decisions.

## Triggers
- When the agent has options flow data and needs directional interpretation
- When user requests options flow analysis or flow-based signals
- When building flow-driven signal pipelines
- When assessing institutional positioning before catalysts

## Inputs
- `flows`: object[] — Raw flow from options-flow-scanner
- `symbol`: string — Underlying symbol
- `aggregation_window_hours`: number — Hours to aggregate (default: 24)
- `min_conviction`: number — Min premium to weight as "high conviction" (default: 100000)

## Outputs
- `directional_bias`: string — "bullish", "bearish", or "neutral"
- `bias_score`: number — -1 to 1 (bearish to bullish)
- `key_strikes`: object[] — Strikes with notable flow and implied move
- `conviction_summary`: object — High/medium/low conviction flow counts
- `metadata`: object — Analyzed flow count, window

## Steps
1. Filter flows by symbol and aggregation_window_hours
2. Classify each flow: call buy / put sell = bullish; put buy / call sell = bearish
3. Weight by premium: larger premium = higher conviction
4. Compute bias_score: (bullish_premium - bearish_premium) / total_premium, normalized to -1..1
5. Map directional_bias from bias_score: >0.3 bullish, <-0.3 bearish, else neutral
6. Aggregate by strike: sum premium per strike, identify clusters (max OI, max flow)
7. Derive key_strikes: top 3-5 by flow premium with implied move if IV available
8. Bucket flows by conviction: high (>min_conviction), medium, low
9. Return directional_bias, bias_score, key_strikes, conviction_summary
10. Optionally compare to historical flow for same symbol (e.g., vs 30d avg)

## Example
```
Input: flows=[...], symbol="NVDA", min_conviction=100000
Output: {
  directional_bias: "bullish",
  bias_score: 0.68,
  key_strikes: [{strike: 950, call_premium: 450000, put_premium: 80000}],
  conviction_summary: {high: 5, medium: 12, low: 6},
  metadata: {flow_count: 23, window_hours: 24}
}
```
