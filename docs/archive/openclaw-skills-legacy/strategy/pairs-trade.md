# Pairs Trade

## Purpose
Identify and execute statistical arbitrage between correlated pairs when spread deviates from historical mean.

## Category
strategy

## Triggers
- When user requests pairs trading or stat arb setups
- When agent detects spread z-score beyond threshold
- When building market-neutral or hedged positions
- When validating cointegration and spread reversion signals

## Inputs
- `pair`: string[] — Two tickers, e.g. ["XOM","CVX"] (string[])
- `lookback_days`: number — Days for spread history (number, default: 60)
- `z_score_entry`: number — Z-score threshold for entry (number, default: 2.0)
- `z_score_exit`: number — Z-score for exit/reversion (number, default: 0.5)
- `hedge_ratio_method`: string — "ols", "kalman", or "rolling" (string)

## Outputs
- `spread`: object — Current spread, mean, std, z-score (object)
- `signal`: string — "long_spread", "short_spread", "flat" (string)
- `hedge_ratio`: number — Shares of pair[1] per share of pair[0] (number)
- `position_sizes`: object — Recommended shares for each leg (object)
- `metadata`: object — Cointegration stats, half-life (object)

## Steps
1. Fetch daily OHLC for both symbols over lookback_days
2. Compute hedge ratio via OLS regression (pair[0] vs pair[1]) or Kalman filter
3. Calculate spread = price[0] - hedge_ratio * price[1]
4. Compute spread mean, std, and current z-score
5. Optionally test cointegration (ADF test); warn if not cointegrated
6. If z-score > z_score_entry: short spread (short pair[0], long pair[1])
7. If z-score < -z_score_entry: long spread (long pair[0], short pair[1])
8. Exit when |z-score| < z_score_exit
9. Return signal, hedge ratio, and position sizes for equal dollar exposure
10. Estimate half-life for expected holding period

## Example
```
Input: pair=["XOM","CVX"], lookback_days=60, z_score_entry=2.0
Output: {
  spread: {value: 2.35, mean: 1.80, std: 0.28, z_score: 1.96},
  signal: "flat",
  hedge_ratio: 1.12,
  metadata: {half_life_days: 8, cointegrated: true}
}
```

## Notes
- Pairs must be cointegrated; correlation alone is insufficient
- Structural breaks can invalidate historical relationship
- Execution: leg both sides simultaneously to avoid directional risk
