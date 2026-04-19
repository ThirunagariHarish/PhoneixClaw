# Skill: Pattern Recognizer

## Purpose
Recognize chart patterns (head-and-shoulders, double top/bottom, triangles, flags) from price action to support technical entry/exit decisions.

## Triggers
- When the agent needs pattern detection for a symbol
- When user requests chart pattern recognition
- When building pattern-based signal pipelines
- When validating technical setups with pattern confirmation

## Inputs
- `symbol`: string — Ticker to analyze
- `timeframe`: string — "15m", "1h", "1d"
- `patterns`: string[] — ["head_shoulders", "double_top", "double_bottom", "triangle", "flag", "all"]
- `lookback_bars`: number — Bars to scan (default: 100)
- `min_pattern_strength`: number — Min confidence 0-1 to report (default: 0.6)

## Outputs
- `detected_patterns`: object[] — Pattern name, type (bullish/bearish), confidence, levels
- `key_levels`: object — Neckline, breakout level, target if applicable
- `metadata`: object — Symbol, timeframe, bars_scanned

## Steps
1. Fetch OHLCV bars via market-data-fetcher
2. Identify swing highs and swing lows (local extrema over N bars)
3. For head-and-shoulders: find 3 peaks, middle highest; neckline from troughs
4. For double top/bottom: two similar highs/lows with trough between
5. For triangles: converging trendlines (ascending, descending, symmetrical)
6. For flags: sharp move (pole) + consolidation channel
7. Compute confidence per pattern: fit quality, symmetry, volume confirmation
8. Filter by min_pattern_strength; sort by confidence descending
9. Extract key_levels: neckline, breakout, measured move target
10. Return detected_patterns, key_levels, metadata

## Example
```
Input: symbol="NVDA", timeframe="1d", patterns=["head_shoulders", "double_top"], lookback_bars=80
Output: {
  detected_patterns: [{name: "head_and_shoulders", type: "bearish", confidence: 0.78, neckline: 865}],
  key_levels: {neckline: 865, breakout: 865, target: 820},
  metadata: {symbol: "NVDA", timeframe: "1d", bars_scanned: 80}
}
```
