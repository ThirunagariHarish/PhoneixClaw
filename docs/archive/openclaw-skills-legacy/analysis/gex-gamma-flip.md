# GEX & Gamma Flip Analysis

## Purpose
Calculate gamma exposure (GEX), identify gamma flip level, and determine dealer hedging direction for options-driven price dynamics.

## Category
analysis

## API Integration
- Consumes: unusual-whales-gex, options OI/volume data, or CME options; Can compute from options chain; No direct API

## Triggers
- When agent needs GEX calculation or gamma flip level
- When user requests dealer hedging, gamma flip, or options-driven levels
- When building support/resistance from GEX
- When assessing dealer positioning (long/short gamma)

## Inputs
- `gex_data`: object — Pre-fetched GEX from unusual-whales-gex (optional)
- `options_oi`: object — Open interest by strike (call/put) if computing from scratch
- `underlying`: string — SPX, SPY, QQQ, or ticker
- `spot_price`: number — Current underlying price
- `include_flip_level`: boolean — Compute gamma flip (default: true)

## Outputs
- `gex`: object — Total GEX, call GEX, put GEX by strike
- `gamma_flip_level`: number — Price where GEX crosses zero
- `dealer_position`: string — "long_gamma_below" | "short_gamma_above" | "at_flip"
- `hedging_direction`: object — Below flip: dealers buy dips; above: sell rallies
- `metadata`: object — Underlying, spot, computed_at

## Steps
1. If gex_data provided, use directly; else compute from options_oi
2. GEX = OI * gamma * 100 * spot^2 (per contract, scaled)
3. Sum GEX by strike; call GEX positive, put GEX negative (typically)
4. Find gamma_flip_level: price where total GEX = 0 (binary search or interpolation)
5. Compare spot to flip: below = dealers long gamma (buy dips), above = short (sell rallies)
6. Derive hedging_direction: amplifies or dampens moves
7. Return GEX, flip level, dealer position, metadata
8. Cache with 1h TTL

## Example
```
Input: gex_data={total:2.5e9, flip:5820}, underlying="SPX", spot_price=5815
Output: {
  gex: {total: 2.5e9, call: 1.8e9, put: 0.7e9},
  gamma_flip_level: 5820,
  dealer_position: "long_gamma_below",
  hedging_direction: {below_flip: "buy_dips_dampens", above_flip: "sell_rallies_amplifies"},
  metadata: {underlying:"SPX", spot:5815, computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- Above flip: negative gamma, dealers sell when market rises -> amplifies
- Below flip: positive gamma, dealers buy when market falls -> dampens
- Flip level is key intraday support/resistance
