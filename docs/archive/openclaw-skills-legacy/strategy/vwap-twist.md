# VWAP Twist

## Purpose
Enhanced VWAP strategy: buy when price and order flow are both above VWAP; sell when both below.

## Category
strategy

## Triggers
- On every bar (1m or 5m) for intraday execution
- When price crosses VWAP with confirming order flow
- When building or reducing positions relative to VWAP benchmark

## Inputs
- price: current price (number)
- vwap: volume-weighted average price (number)
- orderFlowImbalance: buy volume minus sell volume (number)
- volume: bar volume (number)
- vwapDistance: price minus VWAP in basis points (number)

## Outputs
- signal: LONG | SHORT | FLAT (string)
- strength: 0–100 confluence strength (number)
- deviationBps: price vs VWAP in bps (number)

## Steps
1. Compute price vs VWAP: above = bullish, below = bearish
2. Compute order flow imbalance: positive = net buying, negative = net selling
3. LONG when price > VWAP and orderFlowImbalance > 0
4. SHORT when price < VWAP and orderFlowImbalance < 0
5. Strength = weighted combo of distance from VWAP and flow magnitude
6. FLAT when price and flow disagree

## Example
```yaml
inputs:
  price: 450.35
  vwap: 449.80
  orderFlowImbalance: 125000
outputs:
  signal: LONG
  strength: 88
  deviationBps: 12.2
```

## Notes
- Use as execution enhancer, not standalone; combine with other signals
- Order flow data must be tick-level or reliable; noisy flow degrades signal
