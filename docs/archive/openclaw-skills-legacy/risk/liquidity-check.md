# Liquidity Check

## Purpose
Check liquidity (bid-ask spread, depth, volume) before placing orders to avoid excessive slippage and ensure executable size.

## Category
risk

## Triggers
- When the agent needs to validate liquidity before placing an order
- When user requests liquidity check or order feasibility
- When executing large orders or illiquid symbols
- When order-placer or iceberg-order-sim need pre-trade liquidity validation

## Inputs
- `symbol`: string — Ticker
- `side`: string — "buy" or "sell"
- `quantity`: number — Order quantity to validate
- `order_type`: string — "market", "limit" (affects slippage assessment)
- `market_data`: object — Optional pre-fetched quote/orderbook; if empty, fetch via market-data-fetcher

## Outputs
- `spread_bps`: number — Bid-ask spread in basis points
- `spread_pct`: number — Spread as % of mid price
- `depth_at_best`: number — Size available at best bid/ask
- `depth_5_levels`: number — Total size in top 5 levels (if available)
- `adv_volume`: number — Average daily volume (optional)
- `order_pct_adv`: number — Order size as % of ADV
- `pass`: boolean — Whether order passes liquidity check
- `warnings`: string[] — Liquidity warnings (e.g., "spread > 50 bps", "order > 10% ADV")
- `metadata`: object — Symbol, computed_at

## Steps
1. Fetch quote (bid, ask, size) and order book if not provided
2. Compute spread_bps: (ask - bid) / mid * 10000
3. Compute spread_pct: (ask - bid) / mid * 100
4. Get depth_at_best: min(bid_size, ask_size) at best prices
5. Get depth_5_levels: sum of size in top 5 levels on relevant side
6. Fetch ADV if available (from market-data-fetcher or cached)
7. Compute order_pct_adv: quantity / ADV * 100
8. Evaluate pass: spread < threshold (e.g., 50 bps), quantity <= depth or acceptable % ADV
9. Build warnings: spread too wide, order > 5% ADV, depth insufficient
10. Return spread_bps, spread_pct, depth_at_best, depth_5_levels, adv_volume, order_pct_adv, pass, warnings, metadata

## Example
```
Input: symbol="NVDA", side="buy", quantity=500, order_type="market"
Output: {
  spread_bps: 2.5,
  spread_pct: 0.025,
  depth_at_best: 1200,
  depth_5_levels: 8500,
  adv_volume: 45000000,
  order_pct_adv: 0.001,
  pass: true,
  warnings: [],
  metadata: {symbol: "NVDA", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Use real-time quote for best accuracy; stale data may mislead
- Thresholds are configurable; typical: spread < 50 bps, order < 5-10% ADV
- For illiquid options, check options chain volume and open interest
