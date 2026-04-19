# IV Rank and Percentile

## Purpose
Calculate IV rank and IV percentile for options to assess whether implied volatility is high or low relative to its recent history, useful for strategy selection and timing.

## Category
analysis

## Triggers
- When the agent needs to assess implied volatility regime for a symbol
- When user requests IV rank or IV percentile
- When selecting between premium-selling vs premium-buying strategies
- When evaluating entry timing for options trades

## Inputs
- `symbol`: string — Underlying ticker
- `iv_current`: number — Current implied volatility (decimal)
- `lookback_days`: number — Days for IV history (default: 252)
- `iv_history`: number[] — Optional pre-fetched IV series; if empty, fetch via market-data-fetcher
- `expiration_target`: string — Optional target expiration for IV (e.g., "30d")

## Outputs
- `iv_rank`: number — (current - 52w low) / (52w high - 52w low) * 100
- `iv_percentile`: number — Percentile of current IV in history (0-100)
- `iv_high_52w`: number — 52-week high IV
- `iv_low_52w`: number — 52-week low IV
- `metadata`: object — Symbol, lookback_days, computed_at

## Steps
1. Fetch IV history if not provided (use options chain or historical IV surface)
2. Filter to relevant expiration if expiration_target specified
3. Compute 52-week (or lookback) high and low IV
4. IV rank: (iv_current - iv_low) / (iv_high - iv_low) * 100
5. IV percentile: % of days in lookback where IV was below current
6. Return iv_rank, iv_percentile, iv_high_52w, iv_low_52w
7. Flag regime: "low" (<25), "neutral" (25-75), "high" (>75)
8. Return metadata with symbol and computed_at

## Example
```
Input: symbol="AAPL", iv_current=0.32, lookback_days=252
Output: {
  iv_rank: 68,
  iv_percentile: 72,
  iv_high_52w: 0.45, iv_low_52w: 0.18,
  regime: "high",
  metadata: {symbol: "AAPL", lookback_days: 252, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- IV rank uses range; IV percentile uses distribution; both can differ
- High IV rank/percentile favors premium-selling; low favors premium-buying
- Requires historical IV data; may need to fetch from options data provider
