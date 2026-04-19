# Sector Rotation

## Purpose
Rotate capital between sectors based on relative strength and momentum to overweight outperforming sectors and underweight laggards.

## Category
strategy

## Triggers
- When user requests sector rotation or macro allocation
- When agent needs to rebalance portfolio by sector
- When building tactical sector overweight/underweight
- When validating sector momentum for allocation shifts

## Inputs
- `sectors`: string[] — Sector ETFs or indices, e.g. ["XLK","XLF","XLE"] (string[])
- `benchmark`: string — Index for relative strength, e.g. "SPY" (string)
- `lookback_days`: number — Period for momentum calc (number, default: 63)
- `ranking_method`: string — "momentum", "relative_strength", "both" (string)
- `rebalance_threshold`: number — Min rank change to trigger (number, optional)

## Outputs
- `ranked_sectors`: object[] — Sectors sorted by strength, strongest first (object[])
- `weights`: object — Suggested allocation % per sector (object)
- `rotations`: object[] — Recommended buys/sells from current allocation (object[])
- `relative_strength`: object — RS vs benchmark per sector (object)
- `metadata`: object — Scan date, benchmark, lookback (object)

## Steps
1. Fetch daily OHLC for sector ETFs and benchmark over lookback_days
2. Compute momentum: total return over period, or ROC
3. Compute relative strength: sector_return / benchmark_return
4. Rank sectors by chosen method (momentum, RS, or composite)
5. Assign weights: higher weight to stronger sectors (e.g., top 3 get 70%)
6. Compare to current allocation; generate rotation trades
7. Apply rebalance_threshold: only suggest trades if rank change exceeds it
8. Return ranked sectors, weights, and rotation recommendations
9. Optionally cap single-sector exposure (e.g., max 30%)

## Example
```
Input: sectors=["XLK","XLF","XLE","XLV","XLY"], benchmark="SPY", lookback_days=63
Output: {
  ranked_sectors: [{symbol: "XLK", momentum: 12.5}, {symbol: "XLF", momentum: 8.2}],
  weights: {XLK: 30, XLF: 25, XLE: 20, XLV: 15, XLY: 10},
  rotations: [{action: "buy", symbol: "XLK", target_weight: 30}],
  metadata: {scanned_at: "2025-03-03", lookback: 63}
}
```

## Notes
- Sector ETFs have overlap; avoid over-concentration in correlated sectors
- Rebalance frequency: monthly or quarterly typical; avoid overtrading
- Consider transaction costs when rotating; batch rebalances
