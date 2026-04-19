# Put/Call Ratio Analysis

## Purpose
Analyze put/call ratio (PCR) for sentiment and contrarian signals from options flow, useful for identifying extremes or confirming market direction.

## Category
analysis

## Triggers
- When the agent needs options-based sentiment for a symbol or index
- When user requests put/call ratio or PCR analysis
- When evaluating contrarian or sentiment-driven signals
- When building options flow into signal pipelines

## Inputs
- `symbol`: string — Ticker or index (e.g., "SPY", "QQQ", "AAPL")
- `pcr_type`: string — "volume", "open_interest", or "premium" (default: volume)
- `scope`: string — "equity", "index", or "all" (for index vs equity options)
- `lookback_days`: number — Days for rolling average (default: 5)
- `options_data`: object — Optional pre-fetched put/call volumes; if empty, fetch via options-flow-scanner

## Outputs
- `pcr_value`: number — Current put/call ratio
- `pcr_pctile`: number — Percentile of current PCR in history (0-100)
- `pcr_sma`: number — Simple moving average of PCR
- `signal`: string — "bullish", "bearish", "neutral", "extreme_fear", "extreme_greed"
- `metadata`: object — Symbol, pcr_type, scope, computed_at

## Steps
1. Fetch put and call volumes (or OI or premium) if not provided
2. Compute PCR: put_volume / call_volume (or equivalent for OI/premium)
3. Compute rolling PCR average for lookback_days
4. Compare current PCR to historical distribution; compute percentile
5. Derive signal: high PCR (extreme puts) → contrarian bullish; low PCR → contrarian bearish
6. Map to regime: extreme_fear (>1.2), bearish (0.9-1.2), neutral (0.7-0.9), bullish (0.5-0.7), extreme_greed (<0.5)
7. Return pcr_value, pcr_pctile, pcr_sma, signal, metadata
8. Optionally compare index PCR vs equity PCR for divergence

## Example
```
Input: symbol="SPY", pcr_type="volume", scope="index", lookback_days=5
Output: {
  pcr_value: 1.15,
  pcr_pctile: 82,
  pcr_sma: 1.02,
  signal: "extreme_fear",
  metadata: {symbol: "SPY", pcr_type: "volume", scope: "index", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Index PCR often more reliable than single-stock PCR
- Volume PCR can be skewed by large hedging; OI PCR may be more stable
- Use as confirmation, not sole signal; combine with technical analysis
