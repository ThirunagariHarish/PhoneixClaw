# Circuit Breaker (Hard)

## Purpose
Hard-coded safety layer: kill all trades if loss exceeds X% or confidence falls below threshold. Non-negotiable risk cutoff.

## Category
risk

## Triggers
- Before any new order is placed (pre-trade check)
- When daily/weekly P&L is evaluated
- When model confidence or signal strength is below threshold
- When user explicitly enables circuit breaker mode

## Inputs
- `loss_limit_pct`: number — Max allowed loss % from peak (e.g., 5)
- `confidence_threshold`: number — Min confidence (0–1) to allow trades (e.g., 0.7)
- `current_pnl_pct`: number — Current period P&L % from peak
- `signal_confidence`: number — Confidence of current signal (0–1)
- `scope`: string — "all" (kill everything), "new_only" (block new, allow exits)
- `cooldown_minutes`: number — Minutes to wait after trip before re-eval (default: 60)

## Outputs
- `circuit_tripped`: boolean — Whether trading is blocked
- `reason`: string — "loss_limit", "confidence", or "ok"
- `allowed_actions`: string[] — ["exit_only"] or [] when tripped
- `cooldown_until`: string — ISO timestamp when re-eval allowed
- `metadata`: object — current_pnl_pct, signal_confidence, limits

## Steps
1. Fetch current_pnl_pct from account/portfolio (or use provided)
2. Fetch signal_confidence from strategy/signal (or use provided)
3. If current_pnl_pct <= -loss_limit_pct: trip circuit, reason="loss_limit"
4. If signal_confidence < confidence_threshold: trip circuit, reason="confidence"
5. If tripped: set allowed_actions = ["exit_only"] if scope="all", else []
6. Set cooldown_until = now + cooldown_minutes
7. Return circuit_tripped, reason, allowed_actions, cooldown_until, metadata
8. Block all new orders when tripped; allow exits/closes if exit_only
9. Log trip event for audit; require manual reset or cooldown expiry

## Example
```
Input: loss_limit_pct=5, confidence_threshold=0.7, current_pnl_pct=-4.2, signal_confidence=0.65
Output: {
  circuit_tripped: true,
  reason: "confidence",
  allowed_actions: ["exit_only"],
  cooldown_until: "2025-03-03T16:00:00Z",
  metadata: {current_pnl_pct: -4.2, signal_confidence: 0.65, loss_limit: 5, conf_threshold: 0.7}
}
```

## Notes
- Hard override: no soft warnings; immediate block when tripped
- Cooldown prevents rapid re-entry; manual override should require explicit user action
- Integrate with max-drawdown-monitor for consistency
