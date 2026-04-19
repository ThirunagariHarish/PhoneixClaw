# Skill: Breakout Detector

## Purpose
Detect price breakouts above resistance or below support (e.g., range highs/lows, key levels) to identify potential trend-initiation entries.

## Triggers
- When the agent needs breakout candidates
- When user requests breakout plays or level breaks
- When building breakout watchlists
- When validating entries at key levels

## Inputs
- `symbols`: string[] — Tickers to scan
- `level_type`: string — "range", "swing_high_low", "prior_day", "custom"
- `lookback`: number — Bars for range/swing calculation (default: 20)
- `confirmation`: string — "close", "volume", "both" — breakout confirmation rule
- `timeframe`: string — "5m", "15m", "1h", "1d"

## Outputs
- `breakouts_up`: object[] — Symbols breaking above resistance with level and price
- `breakouts_down`: object[] — Symbols breaking below support
- `levels`: object — Per-symbol support/resistance levels
- `metadata`: object — Scan time, level_type, lookback

## Steps
1. Fetch OHLCV for symbols via market-data-fetcher
2. Compute levels: range high/low, swing highs/lows, or prior day H/L
3. For each symbol, compare current price to levels
4. Breakout up: close > resistance with optional volume confirmation
5. Breakout down: close < support with optional volume confirmation
6. Filter by confirmation rule (close, volume spike, or both)
7. Attach level value, breakout price, and volume ratio
8. Return breakouts_up, breakouts_down, and levels
9. Cache results with short TTL

## Example
```
Input: symbols=["NVDA","AAPL"], level_type="range", lookback=20, timeframe="15m"
Output: {
  breakouts_up: [{symbol: "NVDA", level: 885, price: 892, volume_ratio: 1.5}],
  breakouts_down: [],
  levels: {NVDA: {support: 860, resistance: 885}, AAPL: {support: 172, resistance: 178}},
  metadata: {scanned_at: "2025-03-03T15:00:00Z"}
}
```
