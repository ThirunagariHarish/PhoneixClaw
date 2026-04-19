# Momentum Scalp

## Purpose
Execute quick momentum scalping trades on 1-5 minute charts using short-term price acceleration and volume confirmation.

## Category
strategy

## Triggers
- When user requests scalp setups or intraday momentum plays
- When agent detects strong short-term momentum on low timeframe
- When building scalping watchlists for session
- When validating quick in-and-out entry signals

## Inputs
- `symbols`: string[] — Tickers to scan (string[])
- `timeframe`: string — Chart interval: "1m", "2m", "5m" (string)
- `momentum_threshold`: number — Min ROC % for entry (number, default: 0.5)
- `volume_multiplier`: number — Volume vs avg required (number, default: 1.5)
- `holding_period_bars`: number — Max bars to hold (number, default: 10)

## Outputs
- `signals`: object[] — Entry/exit signals with price and rationale (object[])
- `scalp_candidates`: object[] — Ranked symbols meeting criteria (object[])
- `risk_reward`: object — Per-signal R:R estimate (object)
- `metadata`: object — Scan time, timeframe, params (object)

## Steps
1. Fetch 1-5 min OHLCV via market-data-fetcher for symbols
2. Compute short ROC (e.g., 3-5 bar) and volume vs 20-bar average
3. Filter symbols where ROC > momentum_threshold and volume > volume_multiplier * avg
4. Apply entry logic: price above VWAP, recent higher highs
5. Define exit: trailing stop or profit target (e.g., 1:1.5 R:R)
6. Rank candidates by momentum strength and volume confirmation
7. Return signals with entry price, stop, target, holding period
8. Cache scan results with 1-min TTL for intraday freshness

## Example
```
Input: symbols=["SPY","QQQ","AAPL"], timeframe="5m", momentum_threshold=0.6, volume_multiplier=2
Output: {
  scalp_candidates: [{symbol: "AAPL", roc: 0.8, vol_ratio: 2.3, entry: 175.20}],
  signals: [{symbol: "AAPL", action: "buy", entry: 175.20, stop: 174.80, target: 175.95}],
  metadata: {scanned_at: "2025-03-03T15:30:00Z", timeframe: "5m"}
}
```

## Notes
- Best during first 2 hours and last hour of session; avoid lunch doldrums
- Requires low-latency execution; slippage can erode scalp edge
- Position size should be small; high frequency means many small wins/losses
