# Skill: Max Drawdown Monitor

## Purpose
Monitor maximum drawdown against configured thresholds and trigger alerts or risk reduction when drawdown limits are approached or exceeded.

## Triggers
- When the agent needs to check current drawdown vs limits
- When user requests drawdown monitoring or status
- When portfolio-risk-assessor or risk dashboard needs drawdown
- When automated risk reduction is triggered by drawdown breach

## Inputs
- `account_value`: number — Current equity
- `peak_value`: number — Historical peak equity (or fetch from DB)
- `drawdown_limit_pct`: number — Max allowed drawdown % (e.g., 10)
- `warning_threshold_pct`: number — Alert threshold before limit (e.g., 8)
- `equity_curve`: number[] — Optional; historical equity for rolling drawdown

## Outputs
- `current_drawdown_pct`: number — Current drawdown from peak
- `status`: string — "ok", "warning", "breach"
- `action_required`: boolean — Whether to reduce risk or halt trading
- `peak_date`: string — Date of peak (if available)
- `metadata`: object — Peak_value, account_value, limit

## Steps
1. Compute current_drawdown_pct = (peak_value - account_value) / peak_value * 100
2. If equity_curve provided: find peak, compute drawdown from peak
3. Determine status: breach if current_drawdown_pct >= drawdown_limit_pct
4. Warning if current_drawdown_pct >= warning_threshold_pct and < limit
5. Ok if below warning_threshold_pct
6. action_required = true if status is "breach" (or "warning" if config says so)
7. Fetch peak_date from equity history if stored
8. Return current_drawdown_pct, status, action_required, peak_date, metadata
9. If breach: emit alert; trigger risk reduction (e.g., close positions, reduce size)
10. Log drawdown for time-series analysis

## Example
```
Input: account_value=92000, peak_value=100000, drawdown_limit_pct=10, warning_threshold_pct=8
Output: {
  current_drawdown_pct: 8.0,
  status: "warning",
  action_required: false,
  peak_date: "2025-02-28",
  metadata: {peak_value: 100000, account_value: 92000, limit: 10}
}
```
