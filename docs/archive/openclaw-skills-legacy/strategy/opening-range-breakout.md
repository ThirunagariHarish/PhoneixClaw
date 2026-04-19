# Opening Range Breakout

## Purpose
Trade breakouts from the first 15 or 30 minutes of the session (opening range) for momentum continuation.

## Category
strategy

## Triggers
- When user requests ORB or opening range breakout strategy
- When agent needs intraday breakout signals from session open
- When building first-hour momentum plays
- When validating breakout direction and confirmation

## Inputs
- `symbols`: string[] — Tickers to scan (string[])
- `orb_minutes`: number — Opening range period: 15 or 30 (number)
- `breakout_confirmation`: string — "close", "candle", "volume" (string)
- `min_range_pct`: number — Min OR width % to avoid chop (number, optional)
- `volume_multiplier`: number — Volume vs avg for confirmation (number, default: 1.2)

## Outputs
- `orb_levels`: object — High and low of opening range per symbol (object)
- `signals`: object[] — Breakout direction, entry, stop, target (object[])
- `breakout_type`: string — "bullish" or "bearish" per symbol (string)
- `metadata`: object — OR start/end time, symbols scanned (object)

## Steps
1. Fetch 1-min or 5-min bars from market open for symbols
2. Define opening range: first orb_minutes (15 or 30) of session
3. Compute OR high and OR low for each symbol
4. Wait for range to complete (or use prior session if backtesting)
5. Detect breakout: price closes above OR high (bullish) or below OR low (bearish)
6. Apply confirmation: require close beyond level, or volume > volume_multiplier * avg
7. Filter: skip if OR width < min_range_pct (e.g., <0.3% = too tight)
8. Entry: on breakout confirmation; stop: opposite OR level
9. Target: 1:1.5 or 1:2 R:R, or OR width as target
10. Return OR levels, breakout signals, and metadata
11. Cache OR levels until range completes

## Example
```
Input: symbols=["SPY","QQQ","AAPL"], orb_minutes=30, breakout_confirmation="close"
Output: {
  orb_levels: {SPY: {high: 512.50, low: 511.20}, AAPL: {high: 175.80, low: 175.10}},
  signals: [{symbol: "SPY", direction: "bullish", entry: 512.55, stop: 511.15, target: 514.00}],
  breakout_type: "bullish",
  metadata: {or_start: "09:30", or_end: "10:00", symbols: 3}
}
```

## Notes
- ORB works best in trending days; choppy days produce false breakouts
- Use volume confirmation to filter low-conviction breakouts
- Consider time-of-day filter: avoid late-day ORB (range may be stale)
