# Dynamic Stop (ATR-Based)

## Purpose
ATR-based dynamic stop loss: widens in high volatility, tightens in calm markets to avoid premature stops or excessive risk.

## Category
risk

## Triggers
- When setting or updating stop loss for a position
- When volatility regime changes (e.g., VIX spike)
- When user requests ATR-based or volatility-adjusted stops
- When trailing stop needs to adapt to market conditions

## Inputs
- `symbol`: string — Symbol for position
- `entry_price`: number — Entry price
- `side`: string — "long" or "short"
- `atr_multiplier`: number — ATR multiplier (e.g., 2.0 for 2x ATR)
- `atr_period`: number — ATR lookback period (default: 14)
- `min_stop_pct`: number — Minimum stop distance % (e.g., 1.5)
- `max_stop_pct`: number — Maximum stop distance % (e.g., 8)
- `trailing`: boolean — Use trailing stop (default: true)
- `current_price`: number — Current price for trailing calc

## Outputs
- `stop_price`: number — Recommended stop price
- `stop_distance_pct`: number — Distance from entry/current as %
- `atr_value`: number — Current ATR used
- `volatility_regime`: string — "low", "normal", "high"
- `metadata`: object — atr_multiplier, period, bounds

## Steps
1. Fetch ATR for symbol (atr_period) from market data or technical-analysis
2. Compute stop_distance = atr_value * atr_multiplier
3. Apply min/max bounds: clamp to min_stop_pct and max_stop_pct of price
4. For long: stop_price = entry_price - stop_distance; for short: stop_price = entry_price + stop_distance
5. If trailing: for long, stop_price = max(stop_price, current_price - stop_distance); for short, stop_price = min(stop_price, current_price + stop_distance)
6. Classify volatility_regime from ATR percentile (e.g., <25%=low, >75%=high)
7. Return stop_price, stop_distance_pct, atr_value, volatility_regime, metadata
8. Pass to stop-loss-manager or bracket-order-builder for order placement

## Example
```
Input: symbol="SPY", entry_price=520, side="long", atr_multiplier=2, current_price=522
Output: {
  stop_price: 514.20,
  stop_distance_pct: 1.5,
  atr_value: 2.90,
  volatility_regime: "normal",
  metadata: {atr_multiplier: 2, period: 14, min_pct: 1.5, max_pct: 8}
}
```

## Notes
- ATR expands in volatility; stop widens to avoid noise-driven exits
- Min/max bounds prevent absurdly tight or wide stops
- Trailing lock-in profits; ensure stop only moves in favorable direction
