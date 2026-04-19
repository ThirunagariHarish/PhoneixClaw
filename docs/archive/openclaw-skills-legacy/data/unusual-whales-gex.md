# Unusual Whales Gamma Exposure (GEX)

## Purpose
Fetch gamma exposure (GEX) data per ticker and index from Unusual Whales for options-driven price dynamics and gamma flip level identification.

## Category
data

## API Integration
- Provider: Unusual Whales; REST API; API key in `Authorization: Bearer <token>`; 120 req/min; $49/mo tier

## Triggers
- When agent needs GEX or gamma flip levels
- When user requests gamma exposure, dealer hedging, or options-driven levels
- When building GEX-based support/resistance
- When assessing dealer positioning and hedging flows

## Inputs
- `symbols`: string[] — Tickers or indices (e.g., SPX, SPY, QQQ, NVDA)
- `granularity`: string — "ticker", "index", "aggregate" (optional)
- `include_flip_level`: boolean — Include gamma flip price (default: true)
- `as_of`: string — ISO date for historical GEX (optional)

## Outputs
- `gex`: object — GEX per symbol: total GEX, call GEX, put GEX
- `gamma_flip_level`: object — Price level where gamma flips (positive to negative)
- `dealer_position`: object — Net dealer gamma exposure (long/short)
- `metadata`: object — Source, as_of date, fetched_at

## Steps
1. Call Unusual Whales GEX endpoint for requested symbols
2. Add API key in Authorization header
3. Respect 120 req/min rate limit
4. Parse GEX: total, call, put, by strike if available
5. Compute or retrieve gamma flip level (price where GEX crosses zero)
6. Derive dealer position: dealer is typically short gamma to retail
7. Return GEX, flip level, dealer position per symbol
8. Cache with 1h TTL; GEX updates intraday

## Example
```
Input: symbols=["SPX","SPY","QQQ"], include_flip_level=true
Output: {
  gex: {SPX: {total: 2.5e9, call: 1.8e9, put: 0.7e9}, SPY: {total: 1.2e9}},
  gamma_flip_level: {SPX: 5820, SPY: 582.50, QQQ: 485.00},
  dealer_position: {SPX: "short_gamma_above_flip"},
  metadata: {source:"unusual-whales", as_of:"2025-03-03", fetched_at:"2025-03-03T15:00:00Z"}
}
```

## Notes
- Gamma flip level is critical for intraday support/resistance
- Above flip: dealers hedge by selling (amplifies moves); below: buying (dampens)
- Index GEX often more stable than single-name
