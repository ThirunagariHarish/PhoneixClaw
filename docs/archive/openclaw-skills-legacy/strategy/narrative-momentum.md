# Narrative Momentum

## Purpose
Trade while "story of the day" sentiment velocity is rising; exit when narrative momentum decays.

## Category
strategy

## Triggers
- When a dominant narrative is identified (news, social, options flow)
- When sentiment velocity (change in sentiment over time) is measurable
- When entering or exiting narrative-driven trades

## Inputs
- narrative: dominant story label (string)
- sentimentScore: current sentiment -1 to 1 (number)
- sentimentVelocity: change in sentiment per hour (number)
- velocityHistory: [velocity1, velocity2, ...] (array)
- holdingPosition: boolean (boolean)

## Outputs
- signal: ENTER | HOLD | EXIT (string)
- momentumPhase: ACCELERATING | PEAK | DECAYING (string)
- confidence: 0–100 (number)
- maxHoldMinutes: suggested hold when entering (number)

## Steps
1. Compute sentiment velocity: rolling change in sentiment over 1–2 hours
2. ACCELERATING: velocity rising and positive; enter or hold
3. PEAK: velocity flat or turning; consider tightening stops
4. DECAYING: velocity falling; exit or reduce
5. ENTER when accelerating and velocity > threshold; EXIT when decaying
6. Max hold = estimate of narrative half-life; typically 2–4 hours

## Example
```yaml
inputs:
  narrative: "AI earnings beat"
  sentimentScore: 0.72
  sentimentVelocity: 0.15
  velocityHistory: [0.08, 0.12, 0.15]
outputs:
  signal: HOLD
  momentumPhase: ACCELERATING
  confidence: 85
  maxHoldMinutes: 180
```

## Notes
- Narrative sentiment is noisy; use multiple sources
- Avoid entering when already at peak; wait for decay then reversal
