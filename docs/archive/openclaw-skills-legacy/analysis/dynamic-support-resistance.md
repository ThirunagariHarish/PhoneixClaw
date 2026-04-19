# Dynamic Support & Resistance

## Purpose
Auto-plot support and resistance levels from volume profiles and price action clustering.

## Category
analysis

## Triggers
- When user requests S/R levels for a symbol
- When building entry/exit zones for a strategy
- When assessing breakout or reversal probability
- When overlaying levels on charts or backtests

## Inputs
- `symbol`: string — Ticker (e.g., SPY, AAPL)
- `ohlcv`: object[] — OHLCV bars (or fetch via ibkr-historical-bars)
- `lookback_bars`: number — Bars for level detection (default: 100)
- `volume_weighted`: boolean — Use volume profile for strength (default: true)
- `cluster_tolerance`: number — Pct tolerance for clustering levels (default: 0.002)
- `min_touches`: number — Min price touches to confirm level (default: 2)

## Outputs
- `support_levels`: number[] — Sorted support prices (strongest first)
- `resistance_levels`: number[] — Sorted resistance prices (strongest first)
- `strength_scores`: object — {level: score} for each level (0–1)
- `volume_nodes`: object[] — Volume profile POC/VAH/VAL if volume_weighted
- `metadata`: object — symbol, lookback, computed_at

## Steps
1. Fetch or accept OHLCV; optionally compute volume profile (POC, VAH, VAL)
2. Cluster price highs/lows within cluster_tolerance; filter by min_touches
3. Score levels by touch count, volume at level, recency
4. Separate support (below spot) and resistance (above spot)
5. Sort by strength; return top N levels per side
6. If volume_weighted: merge volume nodes with price-action clusters
7. Return support_levels, resistance_levels, strength_scores, volume_nodes, metadata
8. Cache with 15m TTL per symbol

## Example
```
Input: symbol="SPY", lookback_bars=100, volume_weighted=true
Output: {
  support_levels: [5780, 5765, 5740],
  resistance_levels: [5825, 5850, 5880],
  strength_scores: {5780: 0.92, 5765: 0.78, 5825: 0.88},
  volume_nodes: [{poc: 5795, vah: 5810, val: 5780}],
  metadata: {symbol: "SPY", lookback: 100, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Integrate with ibkr-historical-bars or polygon-snapshot for OHLCV
- Volume profile improves accuracy in ranging markets
- Levels can flip (support becomes resistance) after break
