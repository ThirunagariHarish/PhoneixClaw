# Market Breadth

## Purpose
Compute market breadth indicators (advance/decline, new highs/lows, breadth ratios) to assess overall market health and divergence from price indices.

## Category
analysis

## Triggers
- When the agent needs broad market health assessment
- When user requests market breadth or advance/decline
- When detecting divergence between price and breadth
- When evaluating market regime for strategy selection

## Inputs
- `universe`: string — "NYSE", "NASDAQ", "S&P500" (default: NYSE)
- `indicators`: string[] — ["advance_decline", "new_highs_lows", "breadth_ratio", "mcclellan"]
- `lookback_days`: number — Days for A/D line and ratios (default: 20)
- `market_data`: object — Optional pre-fetched breadth data; if empty, fetch via market-data-fetcher

## Outputs
- `advance_decline`: object — Advances, declines, net, cumulative A/D line
- `new_highs_lows`: object — New highs, new lows, net
- `breadth_ratio`: number — % of stocks above 50-day MA
- `mcclellan_oscillator`: number — If requested; short-term breadth momentum
- `breadth_signal`: string — "bullish", "bearish", "neutral", "divergence"
- `metadata`: object — Universe, computed_at

## Steps
1. Fetch advance/decline counts and new highs/lows if not provided
2. Compute net advance-decline: advances - declines
3. Compute cumulative A/D line: running sum of net A/D
4. Compute new highs - new lows
5. Breadth ratio: % of stocks above 50-day MA (requires constituent data)
6. McClellan oscillator: 19-day EMA of net A/D minus 39-day EMA (if requested)
7. Compare breadth to price index (e.g., SPY); flag divergence if price up but breadth down
8. Derive breadth_signal from ratios and divergence
9. Return all requested indicators and metadata
10. Cache results with short TTL; breadth data updates intraday

## Example
```
Input: universe="NYSE", indicators=["advance_decline", "new_highs_lows", "breadth_ratio"]
Output: {
  advance_decline: {advances: 1850, declines: 1420, net: 430, cumulative_line: 24500},
  new_highs_lows: {highs: 85, lows: 42, net: 43},
  breadth_ratio: 62.5,
  breadth_signal: "bullish",
  metadata: {universe: "NYSE", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- NYSE breadth often includes ETFs and preferreds; NASDAQ is pure equities
- Divergence (price up, breadth down) can precede corrections
- Requires access to breadth data feed; may need alternative data provider
