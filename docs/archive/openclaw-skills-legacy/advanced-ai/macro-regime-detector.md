# Macro Regime Detector

## Purpose
Detect macro regime: hawkish/dovish Fed, inflation up/down, risk-on/risk-off to adapt strategy and positioning.

## Category
advanced-ai

## Triggers
- When evaluating market environment for strategy selection
- When user requests macro regime or Fed stance
- When adjusting risk or sector exposure based on regime
- Periodically (e.g., daily) for regime dashboard

## Inputs
- `data_sources`: object — Optional: {fed_funds, cpi, unemployment, dxy, vix, spy} or fetch
- `lookback_days`: number — Days for regime calc (default: 90)
- `indicators`: string[] — ["fed_stance", "inflation_trend", "risk_sentiment"] or "all"
- `output_granularity`: string — "binary", "score", "full" (default: "score")

## Outputs
- `fed_stance`: string — "hawkish", "dovish", "neutral"
- `inflation_trend`: string — "rising", "falling", "stable"
- `risk_sentiment`: string — "risk_on", "risk_off", "neutral"
- `scores`: object — {fed: 0.7, inflation: -0.3, risk: 0.5} (-1 to 1)
- `regime_label`: string — Composite label (e.g., "dovish_falling_inflation_risk_on")
- `confidence`: number — Regime confidence (0–1)
- `metadata`: object — data_sources, lookback, computed_at

## Steps
1. Fetch data: Fed funds rate, CPI, unemployment, DXY, VIX, SPY (or use provided)
2. Fed stance: rate changes, dot plot; hawkish = rising/stable high; dovish = cuts
3. Inflation trend: CPI YoY direction; rising = hawkish pressure
4. Risk sentiment: VIX level, SPY trend, credit spreads; risk_off = high VIX, SPY down
5. Compute scores: normalize to -1..1 per dimension
6. Apply thresholds for binary labels
7. regime_label = fed_stance + inflation_trend + risk_sentiment
8. confidence = consistency of signals over lookback
9. Return fed_stance, inflation_trend, risk_sentiment, scores, regime_label, confidence, metadata
10. Cache result; refresh on schedule or data update

## Example
```
Input: lookback_days=90, indicators="all", output_granularity="score"
Output: {
  fed_stance: "dovish",
  inflation_trend: "falling",
  risk_sentiment: "risk_on",
  scores: {fed: -0.6, inflation: -0.4, risk: 0.7},
  regime_label: "dovish_falling_inflation_risk_on",
  confidence: 0.82,
  metadata: {lookback: 90, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Data from FRED, Fed, BLS; use bond-yield-fetch, fred-economic-data
- Regime changes lag; use leading indicators when available
- Integrate with adaptive-model-selector for model switching by regime
