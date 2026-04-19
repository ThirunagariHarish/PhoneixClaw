# Regime Adaptive

## Purpose
Switch strategy parameters based on detected market regime (trending, mean-reverting, volatile, quiet).

## Category
strategy

## Triggers
- When regime may have changed (e.g., every 30–60 min)
- Before applying strategy parameters
- When performance degrades and regime shift suspected

## Inputs
- returns: recent price returns (array)
- volumeProfile: volume distribution (object)
- vix: current VIX (number)
- adx: ADX or trend strength (number)
- lookback: bars for regime detection (number)

## Outputs
- regime: TRENDING | MEAN_REVERTING | HIGH_VOL | LOW_VOL (string)
- regimeParams: {strategy, stopMultiplier, holdTime, ...} (object)
- confidence: 0–100 (number)
- transitionWarning: true if regime change detected (boolean)

## Steps
1. Compute metrics: trend strength (ADX), mean reversion (autocorr), vol (VIX/realized)
2. TRENDING: ADX > 25; use trend-following, wider stops
3. MEAN_REVERTING: ADX < 20, high autocorr; use mean reversion, tighter targets
4. HIGH_VOL: VIX > 22; reduce size, wider stops
5. LOW_VOL: VIX < 15; normal size, tighter stops
6. Output regime-specific params; flag transition when regime change

## Example
```yaml
inputs:
  adx: 32
  vix: 18
  lookback: 60
outputs:
  regime: TRENDING
  regimeParams:
    strategy: TREND_FOLLOW
    stopMultiplier: 1.2
    holdTime: 45
  confidence: 82
  transitionWarning: false
```

## Notes
- Regime detection is lagging; avoid overfitting to recent bars
- Blend regimes at boundaries; avoid hard switches
