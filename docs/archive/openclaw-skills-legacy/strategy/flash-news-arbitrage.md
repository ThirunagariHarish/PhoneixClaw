# Flash News Arbitrage

## Purpose
Sub-second headline → historical reaction matching → entry based on how similar headlines moved the market before.

## Category
strategy

## Triggers
- When high-impact headline is ingested (earnings, Fed, macro)
- When headline matches historical event type and entity
- Within 1–5 seconds of headline release

## Inputs
- headline: raw headline text (string)
- entity: ticker or asset (string)
- eventType: EARNINGS | FED | MACRO | SECTOR | OTHER (string)
- historicalReactions: [{headline, return1m, return5m}, ...] (array)
- latencyMs: time since headline (number)

## Outputs
- signal: LONG | SHORT | FLAT (string)
- expectedReturn1m: historical avg 1m return (number)
- confidence: 0–100 match quality (number)
- maxHoldSeconds: suggested hold (number)

## Steps
1. Parse headline: entity, event type, sentiment
2. Match to historical corpus: similar headlines and their 1m/5m returns
3. Compute expected return from matched reactions; require n >= 5 matches
4. LONG when expected return > 0.3%; SHORT when < -0.3%
5. Entry within 2 seconds; exit at 1m or when target hit
6. Confidence = match count and similarity score

## Example
```yaml
inputs:
  headline: "Fed holds rates, signals one cut in 2025"
  entity: SPY
  eventType: FED
  historicalReactions: [{return1m: 0.4}, {return1m: 0.6}, ...]
outputs:
  signal: LONG
  expectedReturn1m: 0.45
  confidence: 82
  maxHoldSeconds: 60
```

## Notes
- Latency critical; stale entries (> 5s) often lose edge
- Historical corpus must be large and curated; avoid overfitting
