# Intraday Exposure Limit

## Purpose
Track and enforce intraday net exposure limits (long vs short, sector, single-name) to cap risk within the trading day.

## Category
risk

## Triggers
- Before placing any new order
- When position changes (fill, close, adjust)
- When user requests exposure status or limit check
- At configurable intervals (e.g., every 5 min) for live monitoring

## Inputs
- `positions`: object[] — Current positions: {symbol, quantity, side, value, sector}
- `pending_orders`: object[] — Open orders not yet filled
- `limits`: object — {net_exposure_pct, max_single_name_pct, max_sector_pct, max_long_pct, max_short_pct}
- `account_value`: number — Current equity for % calculations
- `proposed_trade`: object — Optional: {symbol, side, quantity} to pre-check

## Outputs
- `net_exposure_pct`: number — Net long/short exposure as % of account
- `utilization`: object — Per-limit utilization (e.g., net_exposure: 0.85)
- `limit_breached`: boolean — Whether any limit is exceeded
- `breached_limits`: string[] — Names of breached limits
- `allowed_quantity`: number — Max quantity for proposed_trade that stays within limits (if provided)
- `metadata`: object — Current exposures, limits, account_value

## Steps
1. Compute net long and net short exposure from positions + pending
2. net_exposure_pct = |long_value - short_value| / account_value * 100
3. Compute single-name exposure % per symbol
4. Compute sector exposure % per sector (if sector_mapping available)
5. Compare each to limits; set limit_breached and breached_limits
6. If proposed_trade: simulate add; compute max quantity that keeps all limits
7. utilization = current / limit for each limit type
8. Return net_exposure_pct, utilization, limit_breached, breached_limits, allowed_quantity, metadata
9. Block order if limit_breached; use allowed_quantity to cap size
10. Log exposure snapshots for audit and limit tuning

## Example
```
Input: positions=[...], limits={net_exposure_pct: 50, max_single_name_pct: 20},
       account_value=100000, proposed_trade={symbol: "NVDA", side: "buy", quantity: 100}
Output: {
  net_exposure_pct: 42,
  utilization: {net_exposure: 0.84, max_single_name: 0.95},
  limit_breached: false,
  breached_limits: [],
  allowed_quantity: 85,
  metadata: {nvda_exposure_pct: 19, account_value: 100000}
}
```

## Notes
- Pending orders should be included to prevent limit breach on fill
- Consider intraday reset (e.g., at market open) vs rolling
- Sector limits require sector_mapping (e.g., from fundamental data)
