# Hindenburg Omen

## Purpose
Technical indicator for potential market crash detection based on new highs/lows and breadth deterioration.

## Category
analysis

## Triggers
- When user requests Hindenburg Omen status
- When assessing market crash or correction risk
- When building risk-off or defensive positioning signals
- Periodically for market health dashboard

## Inputs
- `universe`: string — "NYSE", "NASDAQ", or "SP500" (default: NYSE)
- `lookback_days`: number — Days to check for omen (default: 30)
- `threshold_new_highs`: number — Min new 52w highs (default: 2.2% of issues)
- `threshold_new_lows`: number — Min new 52w lows (default: 2.2% of issues)
- `mccllellan_confirm`: boolean — Require McClellan Oscillator confirmation (default: false)
- `breadth_data`: object — Optional pre-fetched new highs/lows, advancing/declining

## Outputs
- `omen_triggered`: boolean — True if omen conditions met
- `new_highs_pct`: number — Pct of issues at 52w high
- `new_lows_pct`: number — Pct of issues at 52w low
- `trigger_count`: number — Omen triggers in lookback (2+ suggests higher risk)
- `mccllellan_confirm`: boolean — McClellan confirmation if requested
- `risk_level`: string — "low", "elevated", "high", "critical"
- `metadata`: object — universe, lookback, computed_at

## Steps
1. Fetch new 52w highs and lows for universe (or use breadth_data)
2. Compute new_highs_pct and new_lows_pct of total issues
3. Omen condition: both > threshold (e.g., 2.2%) on same day
4. Count trigger_count: days meeting condition in lookback
5. If mccllellan_confirm: fetch McClellan Oscillator; confirm if negative
6. risk_level: 0 triggers=low, 1=elevated, 2=high, 3+=critical
7. Return omen_triggered, new_highs_pct, new_lows_pct, trigger_count, risk_level, metadata
8. Cache with 1d TTL

## Example
```
Input: universe="NYSE", lookback_days=30
Output: {
  omen_triggered: true,
  new_highs_pct: 2.8,
  new_lows_pct: 2.5,
  trigger_count: 2,
  mccllellan_confirm: true,
  risk_level: "high",
  metadata: {universe: "NYSE", lookback: 30, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Requires market breadth data; use market-breadth or advance-decline skills
- Historical false positive rate is high; use as one input, not sole signal
- Combine with macro-regime-detector for regime context
