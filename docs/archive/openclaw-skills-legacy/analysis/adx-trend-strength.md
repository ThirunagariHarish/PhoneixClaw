# ADX Trend Strength

## Purpose
ADX-based filter to identify trending vs choppy markets for strategy selection.

## Category
analysis

## Triggers
- When user requests trend strength for a symbol
- When filtering strategies (trend-following vs mean-reversion)
- When assessing if breakout or reversal setup is valid
- When building regime-aware position sizing

## Inputs
- `symbol`: string — Ticker to analyze
- `ohlcv`: object[] — OHLCV bars (or fetch)
- `period`: number — ADX period (default: 14)
- `trend_threshold`: number — ADX above = trending (default: 25)
- `strong_trend_threshold`: number — ADX above = strong trend (default: 40)
- `include_di`: boolean — Include +DI/-DI (default: true)

## Outputs
- `adx`: number — ADX value (0–100)
- `plus_di`: number — +DI value (if include_di)
- `minus_di`: number — -DI value (if include_di)
- `market_state`: string — "trending", "choppy", "strong_trend"
- `trend_direction`: string — "bullish", "bearish", "neutral" (from +DI vs -DI)
- `metadata`: object — symbol, period, computed_at

## Steps
1. Fetch or accept OHLCV; compute +DM, -DM, TR (True Range)
2. Smooth with Wilder's method: +DM14, -DM14, TR14
3. +DI = 100 * (+DM14 / TR14), -DI = 100 * (-DM14 / TR14)
4. DX = 100 * |+DI - -DI| / (+DI + -DI)
5. ADX = smoothed DX (typically 14-period)
6. market_state: ADX < trend_threshold = choppy, else trending; ADX >= strong_trend_threshold = strong_trend
7. trend_direction: +DI > -DI = bullish, +DI < -DI = bearish, else neutral
8. Return adx, plus_di, minus_di, market_state, trend_direction, metadata
9. Cache with 15m TTL

## Example
```
Input: symbol="SPY", period=14, trend_threshold=25
Output: {
  adx: 32,
  plus_di: 28,
  minus_di: 18,
  market_state: "trending",
  trend_direction: "bullish",
  metadata: {symbol: "SPY", period: 14, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- ADX > 25: favor trend-following; ADX < 25: favor mean-reversion
- +DI/-DI crossovers can signal trend changes
- Integrate with volatility-regime-classifier for full regime view
