# Skill: Volatility-Adjusted Sizer

## Purpose
Adjust position size based on current volatility (ATR, implied vol) so that risk per trade remains consistent across different volatility regimes.

## Triggers
- When the agent needs volatility-adjusted position sizing
- When user requests vol-based sizing
- When position-sizer output should be scaled by volatility
- When ATR or IV is elevated and standard sizing would over-risk

## Inputs
- `base_quantity`: number — Quantity from position-sizer (unadjusted)
- `symbol`: string — Ticker for volatility lookup
- `current_atr`: number — Current ATR (or fetch via technical-analysis)
- `baseline_atr`: number — Normal/baseline ATR for scaling (e.g., 20d avg)
- `method`: string — "atr_ratio", "iv_ratio", or "hybrid"
- `max_adjustment`: number — Max scale factor (e.g., 1.5 = never more than 1.5x base)

## Outputs
- `adjusted_quantity`: number — Volatility-adjusted share count
- `scale_factor`: number — Multiplier applied (e.g., 0.8)
- `metadata`: object — current_atr, baseline_atr, method

## Steps
1. Fetch current_atr if not provided (technical-analysis, 14-period ATR)
2. Fetch baseline_atr if not provided (e.g., 20-day average ATR)
3. For "atr_ratio": scale_factor = baseline_atr / current_atr
4. Higher current ATR -> smaller position; lower ATR -> larger position
5. For "iv_ratio": use implied vol from options if available; same logic
6. For "hybrid": blend ATR and IV; weight by config
7. Clamp scale_factor: min 0.5, max max_adjustment (avoid over-sizing)
8. adjusted_quantity = round(base_quantity * scale_factor)
9. Ensure adjusted_quantity >= 1 if base_quantity > 0; else 0
10. Return adjusted_quantity, scale_factor, metadata

## Example
```
Input: base_quantity=100, symbol="NVDA", current_atr=12, baseline_atr=10, method="atr_ratio"
Output: {
  adjusted_quantity: 83,
  scale_factor: 0.833,
  metadata: {current_atr: 12, baseline_atr: 10, method: "atr_ratio"}
}
```
