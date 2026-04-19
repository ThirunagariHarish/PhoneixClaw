# Skill: Trailing Stop Calculator

## Purpose
Calculate dynamic trailing stops based on price movement, ATR, or percentage to lock in profits while allowing winners to extend.

## Triggers
- When the agent needs to compute a trailing stop level for a position
- When user requests trailing stop calculation
- When stop-loss-manager needs updated stop from trailing logic
- When position has moved favorably and stop should trail

## Inputs
- `position`: object — Symbol, side, entry_price, current_price, current_stop
- `method`: string — "atr", "percent", "swing", or "hybrid"
- `atr_multiplier`: number — For ATR method (default: 2)
- `trail_percent`: number — For percent method (default: 5)
- `lookback_bars`: number — For swing method (default: 10)

## Outputs
- `trailing_stop`: number — Recommended stop price
- `distance_from_price`: number — Distance in $ and %
- `metadata`: object — Method used, ATR value, high_water_mark

## Steps
1. Fetch current price and ATR if method uses ATR (via market-data-fetcher, technical-analysis)
2. For "atr": trailing_stop = current_price - (atr * atr_multiplier) for long; add for short
3. For "percent": trailing_stop = current_price * (1 - trail_percent/100) for long
4. For "swing": find recent swing low (long) or swing high (short) over lookback_bars
5. For "hybrid": use ATR for initial distance, percent as floor/ceiling
6. Ensure trailing stop never moves against position: for long, stop >= current_stop
7. Ensure stop is below current price (long) or above (short)
8. Compute distance_from_price: abs(current_price - trailing_stop)
9. Return trailing_stop, distance_from_price, metadata
10. Pass to stop-loss-manager for order placement if warranted

## Example
```
Input: position={symbol: "NVDA", side: "long", entry_price: 875, current_price: 895, current_stop: 860}, method="atr", atr_multiplier=2
Output: {
  trailing_stop: 877.40,
  distance_from_price: 17.60,
  metadata: {method: "atr", atr: 8.80, high_water_mark: 895}
}
```
