# Gap Fill

## Purpose
Trade gap fills on the opening range: identify overnight gaps and execute when price reverts toward prior close or gap midpoint.

## Category
strategy

## Triggers
- When user requests gap fill or opening range strategies
- When agent detects significant overnight gap (e.g., >0.5%)
- When building intraday mean-reversion plays
- When validating gap fill probability and entry levels

## Inputs
- `symbols`: string[] — Tickers to scan for gaps (string[])
- `gap_threshold_pct`: number — Min gap size to trade, e.g. 0.5 (number)
- `fill_target`: string — "full", "half", "prior_close" (string)
- `time_window`: string — Minutes after open to consider, e.g. "30" (string)
- `volume_filter`: boolean — Require above-avg volume (boolean, optional)

## Outputs
- `gaps`: object[] — Symbols with gap size, direction, prior close (object[])
- `signals`: object[] — Entry levels, stop, target for each gap (object[])
- `fill_probability`: object — Historical fill rate % per symbol (object)
- `metadata`: object — Scan time, gap threshold, time window (object)

## Steps
1. Fetch prior day close and current pre-market or open price for symbols
2. Compute gap % = (open - prior_close) / prior_close * 100
3. Filter gaps where |gap %| >= gap_threshold_pct
4. Classify: gap up (positive) vs gap down (negative)
5. For gap up: target fill = prior_close or gap midpoint; short bias
6. For gap down: target fill = prior_close or gap midpoint; long bias
7. Define entry: pullback toward fill target in first time_window minutes
8. Set stop: beyond gap extreme (e.g., above open for gap down short)
9. Set target: fill_target level (full, half, or prior_close)
10. Optionally fetch historical gap fill rates for confidence
11. Apply volume_filter if requested
12. Return gaps, signals, and fill probability

## Example
```
Input: symbols=["AAPL","NVDA","TSLA"], gap_threshold_pct=1.0, fill_target="half", time_window="30"
Output: {
  gaps: [{symbol: "TSLA", gap_pct: -2.1, prior_close: 245.50, open: 240.35}],
  signals: [{symbol: "TSLA", direction: "long", entry: 241.50, stop: 239.00, target: 242.93}],
  fill_probability: {TSLA: 0.62},
  metadata: {scanned_at: "2025-03-03T09:35:00Z"}
}
```

## Notes
- Gap fills more likely in ranging markets; trends can see gaps extend
- First 15-30 min often volatile; use limit orders at calculated levels
- Earnings and news gaps may not fill; filter by catalyst
