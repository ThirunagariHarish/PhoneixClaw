# MOC Drift Trade

## Purpose
Front-run MOC (Market-On-Close) imbalance drift in the final 10 minutes by trading in direction of imbalance.

## Category
strategy

## Triggers
- In final 10 minutes of regular session (3:50–4:00 PM ET)
- When MOC imbalance is published and exceeds threshold
- When imbalance direction is consistent with prior 5-min drift

## Inputs
- mocImbalance: buy vs sell imbalance in shares (number)
- imbalanceThreshold: min imbalance for signal (number)
- priceDrift5m: 5-min price change (number)
- volume5m: volume in last 5 min (number)
- vwap: volume-weighted average price (number)

## Outputs
- signal: LONG | SHORT | FLAT (string)
- confidence: 0–100 (number)
- targetBasis: expected close vs current (number)
- maxHold: seconds to hold (number)

## Steps
1. Fetch MOC imbalance; require |imbalance| > threshold (e.g., 500k shares for SPY)
2. Align with 5-min drift: long when imbalance > 0 and drift > 0
3. Enter in direction of imbalance; target capture of 50–80% of imbalance move
4. Exit at or before 4:00 PM; do not hold through close
5. Reduce size when volume is thin; imbalance can reverse on low liquidity

## Example
```yaml
inputs:
  mocImbalance: 1200000
  priceDrift5m: 0.15
  imbalanceThreshold: 500000
outputs:
  signal: LONG
  confidence: 82
  targetBasis: 0.12
  maxHold: 600
```

## Notes
- MOC data may be delayed; verify source latency
- Avoid on quarterly rebalance days; imbalance can be noisy
