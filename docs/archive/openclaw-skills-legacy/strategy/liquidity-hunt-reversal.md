# Liquidity Hunt Reversal

## Purpose
Detect and fade stop-hunt / liquidity grab spikes when price briefly breaches key levels then reverses.

## Category
strategy

## Triggers
- When price spikes through prior swing high/low then reverses within 1–5 min
- When volume spike accompanies the breach but fails to follow through
- When key levels (VWAP, prior day high/low) are violated then reclaimed

## Inputs
- price: current price (number)
- keyLevel: breached level (number)
- breachDirection: ABOVE | BELOW (string)
- volumeSpike: current bar vol vs 20-bar avg (number)
- reversalConfirmed: price back inside level (boolean)
- timeSinceBreach: seconds since breach (number)

## Outputs
- signal: FADE_LONG | FADE_SHORT | FLAT (string)
- confidence: 0–100 (number)
- invalidationLevel: level that invalidates fade (number)
- targetLevel: mean reversion target (number)

## Steps
1. Detect breach: price beyond key level (swing, VWAP, PDL/PDH)
2. Require volume spike > 1.5x avg; suggests stop hunt
3. Wait for reversal: price back inside level within 5 min
4. FADE_LONG when breach was below and reversed up; FADE_SHORT when above and reversed down
5. Target prior level or VWAP; stop beyond breach extreme

## Example
```yaml
inputs:
  keyLevel: 448.50
  breachDirection: BELOW
  reversalConfirmed: true
  volumeSpike: 2.1
outputs:
  signal: FADE_LONG
  confidence: 78
  invalidationLevel: 447.80
  targetLevel: 449.20
```

## Notes
- Not all breaches are stop hunts; require confirmation
- Avoid fading in strong trends; only in chop or range
