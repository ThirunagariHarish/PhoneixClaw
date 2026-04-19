# IBKR Historical Bars

## Purpose
Fetch historical OHLCV bars from Interactive Brokers for intraday and daily analysis via reqHistoricalData.

## Category
data

## API Integration
- Provider: Interactive Brokers TWS; reqHistoricalData via ib_async; Free with IBKR account; 60 concurrent requests max; No explicit rate limit for historical

## Triggers
- When agent needs historical OHLCV data
- When user requests intraday or daily bars for backtesting
- When building charts, indicators, or technical analysis
- When computing returns, volatility, or patterns

## Inputs
- `symbols`: string[] — Tickers (e.g., AAPL, SPY)
- `bar_size`: string — "1 min", "5 mins", "15 mins", "1 hour", "1 day"
- `duration`: string — "1 D", "1 W", "1 M", "1 Y"
- `end_datetime`: string — ISO datetime for bar end (optional; default: now)
- `rth_only`: boolean — Regular trading hours only (default: true for intraday)
- `contract_type`: string — "stock", "future", "option" (default: stock)

## Outputs
- `bars`: object — Symbol -> array of {open, high, low, close, volume, time}
- `metadata`: object — Bar size, duration, symbol count, source

## Steps
1. Connect to TWS via ib_async
2. Create contract for each symbol
3. Call reqHistoricalData with bar_size, duration, end_datetime
4. Set useRTH=1 for regular hours if rth_only
5. Wait for historicalDataEnd callback
6. Parse bars: open, high, low, close, volume, barTime
7. Handle gaps: IBKR may return incomplete bars for current period
8. Normalize timestamps to ISO
9. Return bars dict and metadata
10. Cache aggressively; historical data immutable

## Example
```
Input: symbols=["AAPL"], bar_size="5 mins", duration="1 D", rth_only=true
Output: {
  bars: {
    AAPL: [
      {open:175.20,high:175.35,low:175.15,close:175.30,volume:12500,time:"2025-03-03T09:30:00Z"},
      {open:175.30,high:175.55,low:175.25,close:175.50,volume:18200,time:"2025-03-03T09:35:00Z"}
    ]
  },
  metadata: {bar_size:"5 mins", duration:"1 D", source:"ibkr"}
}
```

## Notes
- Intraday bars limited to ~1 year lookback; daily to ~10 years
- 1 min bars: max 1 D duration; 5 min: ~1 W; 1 day: years
- Incomplete bar at current time excluded by default
