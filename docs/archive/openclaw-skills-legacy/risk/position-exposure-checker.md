# Skill: Position Exposure Checker

## Purpose
Check concentration and exposure limits: single-name, sector, and correlation-based limits to prevent over-concentration and ensure diversification.

## Triggers
- When the agent needs to validate position exposure before adding a trade
- When user requests exposure check or concentration analysis
- When trade-intent-generator applies pre-trade risk checks
- When portfolio-risk-assessor needs exposure breakdown

## Inputs
- `positions`: object[] — Current positions with symbol, value, sector (if available)
- `proposed_trade`: object — Symbol, side, quantity, value (optional)
- `limits`: object — max_single_pct, max_sector_pct, max_correlated_pct
- `account_value`: number — Total equity

## Outputs
- `pass`: boolean — Whether exposure limits are satisfied
- `violations`: string[] — List of limit violations
- `exposure_by_symbol`: object — Symbol -> % of portfolio
- `exposure_by_sector`: object — Sector -> % of portfolio
- `metadata`: object — Limits used, account_value

## Steps
1. Compute current exposure: value per position / account_value
2. If proposed_trade: add to positions for "what-if" check
3. exposure_by_symbol: each symbol's value / account_value
4. Fetch sector for each symbol (from fundamentals or config)
5. exposure_by_sector: sum value per sector / account_value
6. Check max_single_pct: any symbol > limit? Add to violations
7. Check max_sector_pct: any sector > limit? Add to violations
8. For max_correlated_pct: use correlation-detector; sum exposure of highly correlated names
9. If any violation: pass = false
10. Return pass, violations, exposure_by_symbol, exposure_by_sector, metadata

## Example
```
Input: positions=[...], proposed_trade={symbol: "NVDA", value: 15000}, limits={max_single_pct: 15}, account_value=100000
Output: {
  pass: false,
  violations: ["NVDA would exceed max_single_pct (15%): projected 18%"],
  exposure_by_symbol: {NVDA: 0.18, AAPL: 0.12, ...},
  exposure_by_sector: {Technology: 0.45, ...},
  metadata: {limits: {max_single_pct: 15}, account_value: 100000}
}
```
