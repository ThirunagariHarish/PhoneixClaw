# Post-Trade Retrospective

## Purpose
Psychological guard — analyze last 3 trades for revenge trading patterns, overtrading, or emotional drift.

## Category
strategy

## Triggers
- After each closed trade
- When 3+ trades completed in session
- When user requests self-check

## Inputs
- lastTrades: [{pnl, outcome, timeSincePrior, size, reason}, ...] (array)
- sessionPnl: total session P&L (number)
- maxTradesPerDay: limit (number)
- timeBetweenTrades: minutes (array)

## Outputs
- warning: REVENGE | OVERTRADING | TILT | OK (string)
- message: human-readable explanation (string)
- suggestedAction: PAUSE | REDUCE_SIZE | CONTINUE | STOP (string)
- cooldownMinutes: minutes to wait (number)

## Steps
1. Check revenge: trade within 5 min of loss, larger size, opposite direction
2. Check overtrading: trade count > maxTradesPerDay or < 2 min between trades
3. Check tilt: 2+ consecutive losses with increasing size
4. REVENGE → PAUSE; OVERTRADING → REDUCE_SIZE; TILT → STOP
5. OK when none detected; cooldown = 0
6. Cooldown = 15–30 min when warning; 60 min for TILT

## Example
```yaml
inputs:
  lastTrades:
    - {pnl: -150, timeSincePrior: 3, size: 2}
    - {pnl: 200, timeSincePrior: 45, size: 1}
  sessionPnl: 50
outputs:
  warning: REVENGE
  message: "Trade 3 min after loss with 2x size — possible revenge"
  suggestedAction: PAUSE
  cooldownMinutes: 20
```

## Notes
- Not a substitute for discipline; use as nudge
- Customize thresholds per user risk tolerance
