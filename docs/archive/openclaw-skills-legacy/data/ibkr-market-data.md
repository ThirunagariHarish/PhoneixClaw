# IBKR Market Data (TWS Streaming)

## Purpose
Stream real-time Level 1 and Level 2 market data from Interactive Brokers TWS via ib_async for live quotes, order book, and tape.

## Category
data

## API Integration
- Provider: Interactive Brokers TWS; Streaming via ib_async (Python); Paper/Live account; Free with IBKR account; No explicit rate limit (TWS throttles internally)

## Triggers
- When agent needs real-time L1/L2 quotes
- When user requests live bid/ask, order book, or tape
- When building order-flow or liquidity analysis
- When executing trades and need current prices

## Inputs
- `symbols`: string[] — Tickers (e.g., AAPL, SPY)
- `data_type`: string — "l1", "l2", "tape", "trades"
- `contract_type`: string — "stock", "future", "option" (default: stock)
- `exchange`: string — Primary exchange (optional)
- `duration`: number — Seconds to stream (optional; 0 = until cancelled)

## Outputs
- `quotes`: object — Bid, ask, last, bid_size, ask_size per symbol
- `order_book`: object — L2 depth (bid/ask levels with sizes)
- `trades`: object[] — Recent trades: price, size, time
- `metadata`: object — Source, exchange, stream_start

## Steps
1. Connect to TWS via ib_async (port 7497 paper, 7496 live)
2. Create Stock/Future/Option contract for each symbol
3. Request market data: reqMktData (L1), reqMktDepth (L2), reqTickByTickData (trades)
4. Subscribe to callbacks; aggregate updates
5. For L2: maintain sorted bid/ask levels
6. For tape: buffer recent trades with price, size, time
7. Stream for duration or until cancel
8. Return latest snapshot: quotes, order_book, trades
9. Disconnect cleanly; handle TWS reconnects

## Example
```
Input: symbols=["AAPL","NVDA"], data_type="l2", duration=30
Output: {
  quotes: {AAPL: {bid:175.48,ask:175.52,last:175.50,bid_size:500,ask_size:300}},
  order_book: {AAPL: {bids:[[175.48,500],[175.47,1200]], asks:[[175.52,300],[175.53,800]]}},
  trades: [{symbol:"AAPL",price:175.50,size:100,time:"2025-03-03T14:30:00Z"}],
  metadata: {source:"ibkr", exchange:"SMART", stream_start:"2025-03-03T14:29:30Z"}
}
```

## Notes
- Requires TWS or IB Gateway running; market data subscriptions enabled
- L2 depth levels configurable (typically 5–10)
- Paper account uses paper data; live requires real-time subscription
