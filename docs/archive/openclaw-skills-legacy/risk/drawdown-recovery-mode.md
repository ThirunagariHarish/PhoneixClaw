# Drawdown Recovery Mode

## Purpose
Enter recovery mode after drawdown: reduce position size, tighten entry criteria, and limit new risk until equity recovers.

## Category
risk

## Triggers
- When max-drawdown-monitor reports breach or warning
- When user manually enables recovery mode
- When daily/weekly loss exceeds threshold
- When equity falls below a trailing peak by X%

## Inputs
- `current_drawdown_pct`: number — Current drawdown from peak
- `recovery_mode_active`: boolean — Whether already in recovery
- `size_reduction_pct`: number — Reduce position size by this % in recovery (e.g., 50)
- `confidence_boost`: number — Require higher confidence for entries (e.g., 0.85 vs 0.7)
- `max_new_positions`: number — Max new positions per day in recovery (default: 2)
- `recovery_exit_pct`: number — Exit recovery when drawdown recovers to this % (e.g., 5)
- `positions_count`: number — Current open positions
- `new_positions_today`: number — Count of new positions opened today

## Outputs
- `recovery_mode_active`: boolean — Whether recovery mode is now active
- `size_multiplier`: number — Position size multiplier (e.g., 0.5 in recovery)
- `min_confidence`: number — Minimum confidence for new entries
- `can_open_new`: boolean — Whether a new position is allowed
- `recovery_exit_eligible`: boolean — Whether drawdown has recovered enough to exit
- `metadata`: object — drawdown, limits, new_positions_today

## Steps
1. If current_drawdown_pct >= threshold (e.g., 8%): set recovery_mode_active = true
2. If recovery_mode_active: size_multiplier = 1 - size_reduction_pct/100
3. min_confidence = base_confidence + confidence_boost (capped at 0.99)
4. can_open_new = (new_positions_today < max_new_positions) && (positions_count < limit)
5. If current_drawdown_pct <= recovery_exit_pct: recovery_exit_eligible = true
6. If recovery_exit_eligible and user confirms (or auto): set recovery_mode_active = false
7. Return recovery_mode_active, size_multiplier, min_confidence, can_open_new, recovery_exit_eligible, metadata
8. Apply size_multiplier in position-sizer; enforce min_confidence in signal-evaluator
9. Block new positions when can_open_new = false
10. Log recovery mode state changes for analysis

## Example
```
Input: current_drawdown_pct=9, recovery_mode_active=true, size_reduction_pct=50,
       max_new_positions=2, new_positions_today=1
Output: {
  recovery_mode_active: true,
  size_multiplier: 0.5,
  min_confidence: 0.85,
  can_open_new: true,
  recovery_exit_eligible: false,
  metadata: {drawdown: 9, new_positions_today: 1, max_new: 2}
}
```

## Notes
- Recovery mode should persist across sessions until explicitly exited
- Gradual exit (e.g., step down size_reduction over time) can smooth transition
- Integrate with circuit-breaker-hard for severe drawdowns
