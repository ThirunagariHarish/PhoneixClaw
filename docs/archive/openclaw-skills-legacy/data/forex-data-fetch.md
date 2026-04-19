# Forex Data Fetch

## Purpose
Fetch forex pair rates, historical data, and cross-rates for currency analysis and FX strategy execution.

## Category
data

## Triggers
- When agent needs forex rates for analysis or backtesting
- When user requests FX quotes, historical rates, or cross-currency pairs
- When building forex trading strategies or hedging currency exposure
- When execution logic requires real-time FX bid/ask or mid rate

## Inputs
- `pairs`: string[] — FX pairs, e.g. ["EUR/USD","GBP/JPY","USD/JPY"] (string[])
- `data_type`: string — "rates", "ohlcv", "spread", or "all" (string)
- `timeframe`: string — For OHLCV: "1m", "5m", "1h", "4h", "1d" (string)
- `start`: string — ISO date for historical start (string, optional)
- `end`: string — ISO date for historical end (string, optional)
- `provider`: string — "oanda", "polygon", "twelve_data", or default (string)

## Outputs
- `rates`: object — Bid, ask, mid per pair (object)
- `ohlcv`: object[] — OHLCV bars when requested (object[])
- `spread`: object — Bid-ask spread in pips per pair (object)
- `metadata`: object — Provider, fetch time, pair count (object)

## Steps
1. Resolve forex data provider from input or config
2. Normalize pair format (e.g., EURUSD vs EUR/USD) per provider
3. For rates: fetch current bid, ask, mid for each pair
4. For OHLCV: call provider candles endpoint with pair, timeframe, start, end
5. Normalize bar format: o, h, l, c, v (volume may be tick volume), t
6. Compute spread = (ask - bid) in pips (4th decimal for most pairs)
7. Handle rate limits and batch requests
8. Cache recent rates with short TTL (FX updates frequently)
9. Return structured output with requested data types and metadata
10. Support cross-rate derivation if base pairs provided

## Example
```
Input: pairs=["EUR/USD","USD/JPY"], data_type="rates"
Output: {
  rates: {"EUR/USD": {bid: 1.0850, ask: 1.0852, mid: 1.0851}, "USD/JPY": {bid: 149.85, ask: 149.87, mid: 149.86}},
  spread: {"EUR/USD": 2, "USD/JPY": 2},
  metadata: {provider: "oanda", fetched_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Forex markets trade 24/5 (closed weekends); check session
- Pip definition varies: JPY pairs use 2nd decimal, others use 4th
- Some providers offer real-time; others have delay for free tier
