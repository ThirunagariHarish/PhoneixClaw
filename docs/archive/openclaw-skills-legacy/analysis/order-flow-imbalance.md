# Order Flow Imbalance

## Purpose
Detect L2 order book imbalance (bid/ask ratio) and potential spoofing from Level 2 market data for flow-based signals.

## Category
analysis

## API Integration
- Consumes: L2 order book from ibkr-market-data, polygon-snapshot, or similar; No direct API; Uses order book depth

## Triggers
- When agent needs order flow imbalance or bid/ask pressure
- When user requests order book analysis, imbalance, or spoofing detection
- When building entry/exit from order flow
- When assessing buy/sell pressure at price levels

## Inputs
- `order_book`: object — L2 depth: {bids: [[price, size]], asks: [[price, size]]}
- `symbol`: string — Ticker for context
- `depth_levels`: number — Levels to consider (default: 5)
- `imbalance_threshold`: number — Min ratio to flag (default: 1.5)
- `spoofing_lookback`: number — Ticks to check for spoofing (optional)

## Outputs
- `bid_ask_ratio`: number — Total bid size / total ask size
- `imbalance_signal`: string — "bid_heavy", "ask_heavy", "balanced"
- `spoofing_alert`: boolean — True if potential spoofing detected
- `level_imbalances`: object[] — Per-level bid/ask ratio
- `metadata`: object — Symbol, depth_levels, computed_at

## Steps
1. Sum bid sizes and ask sizes over top N levels
2. Compute bid_ask_ratio = sum(bids) / sum(asks)
3. Derive imbalance_signal: >1.2 bid_heavy, <0.8 ask_heavy, else balanced
4. For spoofing: detect large size at level that disappears quickly (requires tick history)
5. Compute per-level imbalances for granular view
6. Return ratio, signal, spoofing_alert, level_imbalances
7. Cache with 1s TTL; order book changes frequently

## Example
```
Input: order_book={bids:[[175.50,500],[175.49,1200]], asks:[[175.52,300],[175.53,800]]}, symbol="AAPL"
Output: {
  bid_ask_ratio: 1.55,
  imbalance_signal: "bid_heavy",
  spoofing_alert: false,
  level_imbalances: [{level:1,ratio:1.67},{level:2,ratio:1.5}],
  metadata: {symbol:"AAPL", depth_levels:5, computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- Spoofing detection requires tick-level history; may not be available
- Bid-heavy often bullish; ask-heavy bearish (not always)
- Use with price action; imbalance can precede moves
