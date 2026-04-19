# Skill: Volume Profile Analyzer

## Purpose
Analyze volume distribution across price levels to identify high-volume nodes (support/resistance), value area, and point of control (POC) for trade placement.

## Triggers
- When the agent needs volume profile for a symbol
- When user requests volume profile, VAH/VAL, or POC
- When building support/resistance levels from volume
- When assessing where price may gravitate (mean reversion to POC)

## Inputs
- `symbol`: string — Ticker to analyze
- `timeframe`: string — "1d", "5d", "1m" (intraday vs multi-day)
- `lookback_bars`: number — Bars to include (default: 20 for daily)
- `value_area_pct`: number — Value area as % of volume (default: 70)

## Outputs
- `poc`: number — Point of control (price level with highest volume)
- `vah`: number — Value area high (top of value area)
- `val`: number — Value area low (bottom of value area)
- `volume_by_price`: object[] — Price level -> volume histogram
- `metadata`: object — Symbol, timeframe, bar_count

## Steps
1. Fetch OHLCV bars via market-data-fetcher (symbol, timeframe, lookback)
2. Build volume distribution: for each bar, distribute volume across price range (high-low)
3. Use tick-based or bin-based aggregation: e.g., 0.01 or 0.1 price bins
4. Sum volume per price level; POC = price level with max volume
5. Compute value area: cumulative volume from POC outward until value_area_pct of total
6. VAH = highest price in value area, VAL = lowest price in value area
7. Build volume_by_price: sorted array of {price, volume} for visualization
8. Optionally compute VWAP for comparison
9. Return poc, vah, val, volume_by_price, metadata
10. Cache per symbol/timeframe with TTL for intraday freshness

## Example
```
Input: symbol="NVDA", timeframe="1d", lookback_bars=20, value_area_pct=70
Output: {
  poc: 872.50,
  vah: 895.00,
  val: 848.00,
  volume_by_price: [{price: 872.50, volume: 2500000}, {price: 870, volume: 1800000}, ...],
  metadata: {symbol: "NVDA", timeframe: "1d", bar_count: 20}
}
```
