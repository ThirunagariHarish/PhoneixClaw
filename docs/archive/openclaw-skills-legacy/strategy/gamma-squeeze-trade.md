# Gamma Squeeze Trade

## Purpose
Detect and trade gamma squeeze setups using 0DTE call volume and VWAP breakout confluence.

## Category
strategy

## Triggers
- When 0DTE call volume spikes above 2x 20-day average
- When price breaks above VWAP with accelerating delta
- When dealer gamma is short (dealers short calls, must buy as spot rises)

## Inputs
- odteCallVolume: 0DTE call OI + volume (number)
- vwap: volume-weighted average price (number)
- spotPrice: current underlying price (number)
- deltaExposure: net dealer delta (number)
- volumeProfile: volume at key levels (object)

## Outputs
- signal: LONG | SHORT | FLAT (string)
- confidence: 0–100 (number)
- targetLevel: price target (number)
- stopLevel: stop loss (number)

## Steps
1. Confirm 0DTE call volume > 2x 20d avg; implies dealer short gamma
2. Require spot > VWAP and rising; breakout confirms squeeze
3. Check delta exposure: negative dealer delta supports squeeze
4. Enter long on confirmed breakout; target next gamma level (strike cluster)
5. Stop below VWAP or prior swing low; trail on momentum

## Example
```yaml
inputs:
  odteCallVolume: 450000
  vwap: 448.50
  spotPrice: 449.20
outputs:
  signal: LONG
  confidence: 78
  targetLevel: 451.00
  stopLevel: 447.80
```

## Notes
- Best in SPX/SPY during first 2 hours; gamma effect weakens into close
- Avoid when VIX > 25; high vol reduces squeeze predictability
