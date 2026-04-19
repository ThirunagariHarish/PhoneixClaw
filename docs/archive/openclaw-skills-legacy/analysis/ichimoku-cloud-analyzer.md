# Ichimoku Cloud Analyzer

## Purpose
Ichimoku Cloud long/short term trend bias analysis for trend-following and signal confirmation.

## Category
analysis

## Triggers
- When user requests Ichimoku analysis for a symbol
- When building trend-following entry/exit signals
- When assessing cloud support/resistance and trend direction
- When screening for cloud breakouts or Kumo twists

## Inputs
- `symbol`: string — Ticker to analyze
- `ohlcv`: object[] — OHLCV bars (or fetch)
- `tenkan_period`: number — Tenkan-sen period (default: 9)
- `kijun_period`: number — Kijun-sen period (default: 26)
- `senkou_b_period`: number — Senkou Span B period (default: 52)
- `displacement`: number — Chikou displacement (default: 26)
- `include_signals`: boolean — Generate buy/sell signals (default: true)

## Outputs
- `trend_bias`: string — "bullish", "bearish", "neutral"
- `price_vs_cloud`: string — "above", "below", "inside"
- `tenkan_kijun_cross`: string — "bullish", "bearish", "none"
- `chikou_position`: string — "above_price", "below_price", "neutral"
- `kumo_twist`: boolean — Cloud color change (potential trend shift)
- `signals`: object[] — [{type, bar_index, strength}] if include_signals
- `cloud_levels`: object — {top, bottom} of cloud at current bar
- `metadata`: object — symbol, periods, computed_at

## Steps
1. Fetch or accept OHLCV; compute Tenkan = (9h high + 9h low)/2, Kijun = (26h high + 26h low)/2
2. Senkou A = (Tenkan + Kijun)/2, displaced +26; Senkou B = (52h high + 52h low)/2, displaced +26
3. Chikou = close displaced -26
4. trend_bias: price above cloud = bullish, below = bearish, inside = neutral
5. tenkan_kijun_cross: Tenkan above Kijun = bullish, below = bearish
6. chikou_position: Chikou above price = bullish confirmation, below = bearish
7. kumo_twist: Senkou A crosses Senkou B
8. Generate signals from crosses and cloud breaks
9. Return trend_bias, price_vs_cloud, tenkan_kijun_cross, chikou_position, kumo_twist, signals, cloud_levels, metadata
10. Cache with 15m TTL

## Example
```
Input: symbol="SPY", include_signals=true
Output: {
  trend_bias: "bullish",
  price_vs_cloud: "above",
  tenkan_kijun_cross: "bullish",
  chikou_position: "above_price",
  kumo_twist: false,
  signals: [{type: "cloud_support", bar_index: 0, strength: 0.85}],
  cloud_levels: {top: 5790, bottom: 5775},
  metadata: {symbol: "SPY", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Integrate with ibkr-historical-bars or polygon-snapshot for OHLCV
- Cloud acts as dynamic S/R; combine with dynamic-support-resistance
- Use with trend-follower for trend confirmation
