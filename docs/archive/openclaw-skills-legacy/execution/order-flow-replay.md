# Order Flow Replay

## Purpose
Replay historical order flow for backtesting execution strategies (TWAP, VWAP, implementation shortfall) against real market data.

## Category
execution

## Triggers
- When backtesting execution algorithms
- When evaluating TWAP/VWAP/smart router performance historically
- When user requests execution simulation or fill analysis
- When calibrating slippage or market impact models

## Inputs
- `order_intent`: object — Historical order: symbol, side, quantity, start_time, end_time
- `market_data`: object[] — OHLCV + tape (trades) for the period
- `execution_strategy`: string — "twap", "vwap", "pov", "implementation_shortfall"
- `params`: object — Strategy params (e.g., slice_count, participation_rate)
- `slippage_model`: string — "fixed_bps", "sqrt_volume", "custom" (default: "sqrt_volume")
- `seed`: number — Random seed for reproducibility (optional)

## Outputs
- `fills`: object[] — Simulated fills: {time, price, quantity, slippage_bps}
- `avg_fill_price`: number — Volume-weighted average fill price
- `slippage_bps`: number — Realized slippage vs arrival price
- `implementation_shortfall_bps`: number — Cost vs decision price (if applicable)
- `participation_pct`: number — % of volume executed (for POV)
- `metadata`: object — Strategy, params, market_data_summary

## Steps
1. Load market_data; validate order_intent overlaps data period
2. Compute arrival_price (mid or last at start_time)
3. Compute decision_price if implementation shortfall (e.g., signal time)
4. Slice order per execution_strategy (TWAP: equal time; VWAP: volume curve)
5. For each slice: simulate fill using tape; apply slippage_model
6. sqrt_volume: slippage ∝ sqrt(quantity/ADV)
7. fixed_bps: constant slippage per fill
8. Aggregate fills; compute avg_fill_price, slippage_bps
9. implementation_shortfall_bps = (avg_fill - decision_price) / decision_price * 10000
10. Return fills, avg_fill_price, slippage_bps, implementation_shortfall_bps, participation_pct, metadata

## Example
```
Input: order_intent={symbol: "NVDA", side: "buy", quantity: 1000, start_time: "2025-02-01T14:00:00Z", end_time: "2025-02-01T15:00:00Z"},
       execution_strategy="twap", params={slice_count: 12}, slippage_model="sqrt_volume"
Output: {
  fills: [{time: "14:05", price: 875.20, quantity: 84, slippage_bps: 3.2}, ...],
  avg_fill_price: 875.45,
  slippage_bps: 5.1,
  implementation_shortfall_bps: 4.8,
  participation_pct: 0.02,
  metadata: {strategy: "twap", slice_count: 12}
}
```

## Notes
- Tape data required for realistic fill simulation; OHLCV alone is approximate
- Slippage models are heuristic; calibrate to live execution data
- Seed enables reproducible backtests for strategy comparison
