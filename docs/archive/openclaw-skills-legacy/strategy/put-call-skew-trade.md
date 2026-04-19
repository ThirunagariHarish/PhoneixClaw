# Put-Call Skew Trade

## Purpose
Trade intraday put/call skew extremes when skew deviates from normal range, signaling fear or complacency.

## Category
strategy

## Triggers
- When put skew (25d put vol minus ATM vol) exceeds 2 std dev
- When call skew compresses (complacency) and reversal likely
- When skew mean-reverts after extreme reading

## Inputs
- putSkew25d: 25-delta put IV minus ATM IV (number)
- callSkew25d: 25-delta call IV minus ATM IV (number)
- skewZScore: z-score of current skew vs 20d (number)
- spotPrice: underlying price (number)
- term: option term (e.g., 0, 1, 7 days) (number)

## Outputs
- signal: LONG_PUTS | LONG_CALLS | SELL_PUTS | SELL_CALLS | FLAT (string)
- confidence: 0–100 (number)
- targetSkew: expected skew reversion level (number)
- expiryBias: preferred expiry (string)

## Steps
1. Compute put and call skew; compare to 20-day distribution
2. Extreme put skew (fear): consider long calls or sell puts for mean reversion
3. Compressed call skew (complacency): consider long puts or sell calls
4. Enter when skewZScore > 2 or < -2; exit when |zScore| < 0.5
5. Prefer 1–7 DTE for intraday; 0DTE for quick reversals

## Example
```yaml
inputs:
  putSkew25d: 4.2
  skewZScore: 2.3
  term: 1
outputs:
  signal: LONG_CALLS
  confidence: 75
  targetSkew: 2.0
  expiryBias: "1DTE"
```

## Notes
- Skew can stay extreme during events; use stops
- Correlate with VIX; skew and VIX often move together
