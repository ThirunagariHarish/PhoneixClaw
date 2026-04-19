# Fibonacci Retracement

## Purpose
Compute Fibonacci retracement levels from swing high/low to identify potential entry, exit, and target zones.

## Category
strategy

## Triggers
- When user requests Fib levels or retracement analysis
- When agent identifies clear swing high and swing low for level calculation
- When building pullback entries in trends
- When validating support/resistance from Fib ratios

## Inputs
- `symbol`: string — Ticker to analyze (string)
- `swing_high`: number — Recent swing high price (number)
- `swing_low`: number — Recent swing low price (number)
- `direction`: string — "bullish" (low to high) or "bearish" (high to low) (string)
- `levels`: number[] — Fib ratios, e.g. [0.236, 0.382, 0.5, 0.618, 0.786] (number[], optional)
- `timeframe`: string — Chart timeframe for context (string)

## Outputs
- `fib_levels`: object — Price at each Fib ratio (object)
- `key_levels`: object[] — 0.382, 0.5, 0.618 with price and role (object[])
- `entry_zones`: object[] — Suggested entry zones (e.g., 0.5-0.618) (object[])
- `targets`: object — Extension levels if applicable (object)
- `metadata`: object — Swing high/low, range, direction (object)

## Steps
1. Validate swing_high > swing_low for bullish; reverse for bearish
2. Compute range = swing_high - swing_low
3. For bullish: retracement from high; level = swing_high - (range * ratio)
4. For bearish: retracement from low; level = swing_low + (range * ratio)
5. Calculate levels for default ratios: 0.236, 0.382, 0.5, 0.618, 0.786
6. Key levels: 0.382 (shallow), 0.5 (mid), 0.618 (deep/golden)
7. Entry zones: 0.5-0.618 common for pullback buys in uptrend
8. Optionally compute extension levels: 1.272, 1.618 for targets
9. Return fib_levels, key_levels, entry_zones, targets
10. Include metadata with swing points and range

## Example
```
Input: symbol="AAPL", swing_high=180, swing_low=165, direction="bullish"
Output: {
  fib_levels: {0.236: 176.46, 0.382: 174.27, 0.5: 172.50, 0.618: 170.73, 0.786: 168.21},
  key_levels: [{ratio: 0.618, price: 170.73, role: "primary_buy_zone"}],
  entry_zones: [{from: 172.50, to: 170.73, label: "0.5-0.618"}],
  targets: {1.272: 184.10, 1.618: 189.30},
  metadata: {range: 15, direction: "bullish"}
}
```

## Notes
- Swing selection is subjective; use consistent rules (e.g., pivot algorithm)
- Fib levels work best in trending markets with clear structure
- Combine with volume or momentum confirmation at levels
