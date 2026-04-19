# Multi-Timeframe Confluence

## Purpose
Entry only when signal confirms on 3 timeframes (1m, 5m, 15m) to filter noise and improve win rate.

## Category
strategy

## Triggers
- When primary signal is generated on any timeframe
- Before entering a trade
- When checking for trade validity

## Inputs
- signal1m: LONG | SHORT | FLAT (string)
- signal5m: LONG | SHORT | FLAT (string)
- signal15m: LONG | SHORT | FLAT (string)
- strength1m: 0–100 (number)
- strength5m: 0–100 (number)
- strength15m: 0–100 (number)

## Outputs
- confluence: true | false (boolean)
- direction: LONG | SHORT (string)
- compositeStrength: 0–100 (number)
- weakestTimeframe: 1m | 5m | 15m (string)
- waitFor: which timeframe to wait for (string)

## Steps
1. Require all three timeframes agree on direction (LONG or SHORT)
2. Confluence = true when signal1m == signal5m == signal15m
3. Composite strength = weighted avg (1m: 0.2, 5m: 0.35, 15m: 0.45)
4. Weakest timeframe = lowest strength; consider waiting for confirmation
5. If not confluent, output waitFor = timeframe that disagrees
6. Reject entry when confluence = false

## Example
```yaml
inputs:
  signal1m: LONG
  signal5m: LONG
  signal15m: LONG
  strength1m: 70
  strength5m: 85
  strength15m: 78
outputs:
  confluence: true
  direction: LONG
  compositeStrength: 79
  weakestTimeframe: 1m
  waitFor: null
```

## Notes
- Confluence reduces false signals but may delay entries
- Use 1m/5m/15m for scalps; 5m/15m/60m for swings
