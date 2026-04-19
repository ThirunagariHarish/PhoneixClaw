# Liquidity Heat Map

## Purpose
Map liquidity concentration at price levels from L2 order book data to identify support/resistance and execution zones.

## Category
analysis

## API Integration
- Consumes: L2 order book from ibkr-market-data, polygon-snapshot; No direct API; Uses order book depth

## Triggers
- When agent needs liquidity concentration or heat map
- When user requests support/resistance from order book
- When assessing execution quality at price levels
- When building levels from institutional size

## Inputs
- `order_book`: object — L2 depth: {bids: [[price, size]], asks: [[price, size]]}
- `symbol`: string — Ticker
- `price_range`: object — {min, max} in price (optional; default: full book)
- `aggregation`: string — "by_level", "by_zone" (zone = round price buckets)
- `zone_size`: number — Price bucket size for zones (e.g., 0.50)

## Outputs
- `heat_map`: object[] — [{price, bid_size, ask_size, total, dominance}]
- `key_levels`: object[] — Levels with highest liquidity (support/resistance)
- `execution_zones`: object[] — Best levels for large orders (high liquidity)
- `metadata`: object — Symbol, levels_analyzed, computed_at

## Steps
1. Parse order book bids and asks
2. Aggregate by price level or zone (round to zone_size)
3. Compute total size (bid + ask) per level
4. Compute dominance: bid_pct vs ask_pct
5. Sort by total liquidity descending
6. Extract key_levels: top N by liquidity
7. Identify execution_zones: high total, balanced bid/ask
8. Return heat_map, key_levels, execution_zones
9. Cache with 5s TTL

## Example
```
Input: order_book={bids:[[175.50,500],[175.49,1200],[175.00,5000]], asks:[[175.52,300],[175.53,800],[176.00,4000]]}, symbol="AAPL"
Output: {
  heat_map: [{price:175.00,bid_size:5000,ask_size:0,total:5000,dominance:"bid"},{price:176.00,bid_size:0,ask_size:4000,total:4000,dominance:"ask"}],
  key_levels: [{price:175.00,size:5000,type:"support"},{price:176.00,size:4000,type:"resistance"}],
  execution_zones: [{price:175.50, total:800, spread:0.02}],
  metadata: {symbol:"AAPL", levels_analyzed:10, computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- Large size at level often acts as magnet or barrier
- Execution zones: high liquidity, tight spread
- Combine with GEX levels for stronger conviction
