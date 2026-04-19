# Skill: Technical Analysis

## Purpose
Run technical indicators (RSI, MACD, Bollinger Bands, etc.) on price data to generate overbought/oversold signals and trend confirmation for trading decisions.

## Triggers
- When the agent needs technical indicator values for a symbol
- When user requests RSI, MACD, Bollinger, or other indicators
- When building technical-based signal pipelines
- When validating entries against momentum or mean-reversion setups

## Inputs
- `symbol`: string — Ticker to analyze
- `indicators`: string[] — ["RSI", "MACD", "BB", "SMA", "EMA", "ATR", "VWAP"]
- `timeframe`: string — "1m", "5m", "15m", "1h", "1d"
- `lookback_periods`: number — Bars to use for calculation (default: 50)
- `ohlcv`: object[] — Optional pre-fetched bars; if empty, fetch via market-data-fetcher

## Outputs
- `indicators`: object — Per-indicator values: RSI, MACD line/signal/histogram, BB upper/lower/mid, etc.
- `signals`: object — Derived signals: "oversold", "overbought", "bullish_cross", "bearish_cross"
- `metadata`: object — Symbol, timeframe, bar_count, computed_at

## Steps
1. Fetch OHLCV bars if not provided (use market-data-fetcher with symbol, timeframe)
2. For RSI: compute 14-period RSI; flag oversold (<30), overbought (>70)
3. For MACD: compute 12/26/9 EMA; derive line, signal, histogram; flag crossovers
4. For Bollinger Bands: 20-period SMA, 2 std dev bands; flag price at upper/lower band
5. For SMA/EMA: compute requested periods (e.g., 9, 20, 50)
6. For ATR: compute 14-period ATR for volatility/stop sizing
7. For VWAP: compute cumulative (price * volume) / cumulative volume if intraday
8. Build signals object: aggregate actionable interpretations
9. Return indicators dict, signals dict, and metadata
10. Cache results per symbol/timeframe with short TTL for efficiency

## Example
```
Input: symbol="NVDA", indicators=["RSI", "MACD", "BB"], timeframe="15m"
Output: {
  indicators: {RSI: 42.3, MACD: {line: 2.1, signal: 1.8, histogram: 0.3}, BB: {upper: 890, lower: 855, mid: 872.5}},
  signals: {RSI: "neutral", MACD: "bullish_cross", BB: "near_lower"},
  metadata: {symbol: "NVDA", timeframe: "15m", bar_count: 50, computed_at: "2025-03-03T15:00:00Z"}
}
```
