# Crypto Data Fetch

## Purpose
Fetch cryptocurrency OHLCV and orderbook data from exchanges or aggregators for analysis and execution.

## Category
data

## Triggers
- When agent needs crypto price data for technical analysis or backtesting
- When user requests crypto quotes, historical bars, or orderbook depth
- When building crypto trading strategies or portfolio tracking
- When execution logic requires real-time crypto bid/ask or last price

## Inputs
- `symbols`: string[] — Pairs, e.g. ["BTC/USD","ETH/USD","SOL/USD"] (string[])
- `data_type`: string — "ohlcv", "orderbook", "ticker", or "all" (string)
- `timeframe`: string — For OHLCV: "1m", "5m", "15m", "1h", "4h", "1d" (string)
- `start`: string — ISO date for historical start (string, optional)
- `end`: string — ISO date for historical end (string, optional)
- `provider`: string — "binance", "coinbase", "polygon", or default (string)

## Outputs
- `ohlcv`: object[] — Open, high, low, close, volume, timestamp per bar (object[])
- `orderbook`: object — Bids and asks with price/size per symbol (object)
- `ticker`: object — Last, bid, ask, 24h change per symbol (object)
- `metadata`: object — Provider, fetch time, symbol count (object)

## Steps
1. Resolve crypto data provider from input or config
2. Normalize symbol format (e.g., BTC-USD vs BTC/USD) per provider
3. For OHLCV: call provider candles endpoint with symbol, timeframe, start, end
4. Normalize bar format: o, h, l, c, v, t (UTC timestamp)
5. For orderbook: fetch top N levels; return bids (desc) and asks (asc)
6. For ticker: fetch last, bid, ask, 24h volume, 24h change
7. Handle rate limits: batch requests, respect provider limits
8. Cache recent data per symbol/timeframe to reduce API calls
9. Return structured output with requested data types and metadata
10. Support multiple providers with fallback if configured

## Example
```
Input: symbols=["BTC/USD","ETH/USD"], data_type="ohlcv", timeframe="1h", start="2025-03-01"
Output: {
  ohlcv: [{symbol: "BTC/USD", o: 62000, h: 62500, l: 61800, c: 62200, v: 1200, t: "2025-03-03T14:00:00Z"}],
  metadata: {provider: "polygon", fetched_at: "2025-03-03T15:00:00Z", symbols: 2}
}
```

## Notes
- Crypto markets 24/7; no session open/close like equities
- Orderbook depth varies by exchange; specify levels if needed
- Some providers require separate API keys for crypto
