# Alpha Vantage Technical Indicators

## Purpose
Fetch technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands) from Alpha Vantage for technical analysis and signal generation.

## Category
data

## API Integration
- Provider: Alpha Vantage; REST API; API key in query param `apikey=`; 25 req/day (free); Free tier

## Triggers
- When agent needs technical indicators (SMA, EMA, RSI, MACD, BBands)
- When user requests technical analysis or indicator values
- When building strategy signals from indicators
- When free tier is acceptable for low-frequency use

## Inputs
- `symbol`: string — Ticker (one per request on free tier)
- `indicator`: string — "SMA", "EMA", "RSI", "MACD", "BBANDS"
- `interval`: string — "daily", "weekly", "1min", "5min", "15min", "30min", "60min"
- `time_period`: number — Lookback period (e.g., 14 for RSI)
- `series_type`: string — "open", "high", "low", "close" (default: close)
- `fast_period`: number — For MACD (optional)
- `slow_period`: number — For MACD (optional)

## Outputs
- `values`: object[] — {date, value} or {date, sma, signal, histogram} for MACD
- `metadata`: object — Indicator, interval, symbol, source

## Steps
1. Map indicator to Alpha Vantage endpoint (e.g., /query?function=RSI)
2. Add apikey, symbol, interval, time_period
3. Respect 25 req/day; cache aggressively; batch when possible
4. Parse response: Technical Analysis object with values
5. For MACD: return MACD line, signal, histogram
6. For BBands: return upper, middle, lower
7. Normalize dates and values
8. Return values array and metadata
9. Cache with 1d TTL for daily; 1h for intraday

## Example
```
Input: symbol="AAPL", indicator="RSI", interval="daily", time_period=14
Output: {
  values: [{date:"2025-03-01",value:58.2},{date:"2025-03-02",value:62.1}],
  metadata: {indicator:"RSI", interval:"daily", symbol:"AAPL", source:"alpha-vantage"}
}
```

## Notes
- 25 req/day free tier; use sparingly; prefer cached or batch
- One symbol per request on free; premium allows batch
- Intraday indicators consume more quota
