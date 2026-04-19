# VWAP Reversion

## Purpose
Identify mean reversion opportunities when price deviates significantly from VWAP and execute trades expecting reversion to the volume-weighted average price.

## Category
strategy

## Triggers
- When user requests VWAP reversion or mean reversion to VWAP
- When agent detects price extended from VWAP (e.g., >1 std)
- When building intraday mean reversion plays
- When validating deviation bands and reversion probability

## Inputs
- `symbols`: string[] — Tickers to evaluate (string[])
- `timeframe`: string — Bar interval: "1m", "5m" (string)
- `deviation_threshold`: number — Std devs from VWAP for entry (number, default: 2.0)
- `reversion_target`: string — "vwap", "vwap_band" (string)
- `max_holding_bars`: number — Max bars before exit (number, default: 30)

## Outputs
- `vwap_values`: object — Current VWAP per symbol (object)
- `deviations`: object — Price deviation in std devs from VWAP (object)
- `signals`: object[] — Long/short signals with entry, stop, target (object[])
- `bands`: object — Upper/lower bands (e.g., ±1, ±2 std) (object)
- `metadata`: object — Session VWAP, scan time (object)

## Steps
1. Fetch intraday bars from session open for symbols (cumulative from open)
2. Compute VWAP = cumsum(price * volume) / cumsum(volume)
3. Compute rolling std of price around VWAP (or use fixed % bands)
4. Calculate current deviation = (price - VWAP) / std
5. If deviation > deviation_threshold: price above VWAP → short signal (revert down)
6. If deviation < -deviation_threshold: price below VWAP → long signal (revert up)
7. Entry: current price; stop: beyond deviation extreme
8. Target: VWAP (full reversion) or VWAP ± 0.5 std (partial)
9. Set max_holding_bars to limit exposure
10. Return VWAP, deviations, signals, and bands
11. Reset VWAP at session open (daily VWAP) or use anchored VWAP if configured

## Example
```
Input: symbols=["AAPL","NVDA"], timeframe="5m", deviation_threshold=2.0
Output: {
  vwap_values: {AAPL: 175.20, NVDA: 878.50},
  deviations: {AAPL: -2.1, NVDA: 0.5},
  signals: [{symbol: "AAPL", direction: "long", entry: 173.80, stop: 172.50, target: 175.20}],
  bands: {AAPL: {upper: 176.50, lower: 173.90}},
  metadata: {session_start: "09:30", scanned_at: "2025-03-03T11:00:00Z"}
}
```

## Notes
- VWAP resets each session; use session-anchored data
- Strong trends can stay extended; combine with trend filter
- Best in range-bound intraday conditions
