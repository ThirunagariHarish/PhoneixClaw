# VIX Mean Reversion

## Purpose
Trade VIX extremes using mean reversion (buy low VIX, hedge/sell high VIX) based on historical percentile.

## Category
advanced-ai

## Triggers
- When VIX is at extreme levels (very low or very high)
- When user requests VIX mean reversion signal
- When evaluating options or volatility strategies
- When black-swan-hedge considers exit (VIX normalize)

## Inputs
- `vix_level`: number — Current VIX (or fetch from market data)
- `vix_history`: number[] — Optional: historical VIX for percentile
- `lookback_days`: number — Days for percentile calc (default: 252)
- `percentile_threshold`: number — Extreme = outside this percentile (default: 10)

## Outputs
- `signal`: string — "buy_vix", "sell_vix", "neutral"
- `percentile`: number — Current VIX percentile (0–100)
- `mean_reversion_bias`: string — "high_reversion_expected", "low_reversion_expected"
- `suggested_action`: string — "long_vix_etf", "short_vix", "put_spread", "hold"
- `metadata`: object — vix_level, lookback, percentile

## Steps
1. Fetch VIX level and history (or use provided)
2. Compute percentile: % of days VIX was below current level
3. If percentile < percentile_threshold: signal="buy_vix", mean_reversion_bias="high_reversion_expected"
4. If percentile > (100 - percentile_threshold): signal="sell_vix", mean_reversion_bias="low_reversion_expected"
5. Else: signal="neutral"
6. suggested_action: buy_vix → long VIX ETF or put spread; sell_vix → short VIX or hedge
7. Return signal, percentile, mean_reversion_bias, suggested_action, metadata

## Example
```
Input: vix_level=12, lookback_days=252, percentile_threshold=10
Output: {
  signal: "buy_vix",
  percentile: 8,
  mean_reversion_bias: "high_reversion_expected",
  suggested_action: "long_vix_etf",
  metadata: {vix_level: 12, lookback: 252, percentile: 8}
}
```

## Notes
- VIX mean reversion is strong; VIX rarely stays at 10 or 40 for long
- Use with black-swan-hedge: exit when VIX normalizes
- Consider VIX futures term structure (contango/backwardation)
