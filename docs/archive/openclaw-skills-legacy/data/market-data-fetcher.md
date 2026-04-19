# Skill: Market Data Fetcher

## Purpose
Fetch real-time and historical market data (OHLCV, quotes, fundamentals) from configured data providers for analysis and execution decisions.

## Triggers
- When the agent needs price data for technical analysis or backtesting
- When user requests market data, quotes, or historical bars
- When execution logic requires real-time bid/ask or last price
- When building data pipelines for strategy research

## Inputs
- `symbols`: string[] — Ticker symbols (e.g., ["AAPL", "NVDA"])
- `data_type`: string — "bars", "quote", "fundamentals", or "all"
- `timeframe`: string — For bars: "1m", "5m", "15m", "1h", "1d"
- `start`: string — ISO date for historical start (optional)
- `end`: string — ISO date for historical end (optional)
- `provider`: string — "alpaca", "polygon", "yahoo", or default

## Outputs
- `bars`: object[] — OHLCV bars when data_type includes "bars"
- `quotes`: object[] — Bid/ask/last when data_type includes "quote"
- `fundamentals`: object — Per-symbol fundamentals when requested
- `metadata`: object — Provider, fetch time, symbol count

## Steps
1. Resolve data provider from input or config (Alpaca, Polygon, Yahoo Finance)
2. Validate symbols: check format, filter invalid tickers
3. For bars: call provider bars endpoint with symbol, timeframe, start, end
4. Normalize bar format: open, high, low, close, volume, timestamp (UTC)
5. For quote: call provider quote endpoint; return bid, ask, last, bid_size, ask_size
6. For fundamentals: fetch PE, market_cap, sector, etc. if provider supports
7. Handle rate limits: batch requests, use websocket for real-time when available
8. Cache recent data per symbol/timeframe to reduce API calls
9. Merge multiple provider responses if fallback logic is configured
10. Return structured output with requested data types and metadata

## Example
```
Input: symbols=["AAPL", "NVDA"], data_type="bars", timeframe="15m", start="2025-03-01", end="2025-03-03"
Output: {
  bars: [{symbol: "AAPL", o: 175.2, h: 176.1, l: 174.8, c: 175.9, v: 1200000, t: "2025-03-03T14:45:00Z"}],
  metadata: {provider: "alpaca", fetched_at: "2025-03-03T15:00:00Z", symbols: 2}
}
```
