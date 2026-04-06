# Rebalancing Skill

## When to Rebalance
The strategy config specifies a `rebalance` schedule (e.g. "daily at 15:45 ET"). At that time, evaluate the current state and rotate if needed.

## EMA Crossover Rebalancing (TQQ/SQQQ Example)

### Daily Check
At 15:45 ET, run `python tools/ema_crossover.py --underlying QQQ --bull TQQ --bear SQQQ --fast 8 --slow 24`.

### Rotation Logic
- If currently in TQQ AND signal flipped to bear: SELL TQQ, BUY SQQQ
- If currently in SQQQ AND signal flipped to bull: SELL SQQQ, BUY TQQ
- If signal hasn't flipped: HOLD current position

### Position Sizing
The strategy is binary — full allocation goes into ONE instrument at a time. Use `position_size_pct: 100` from config.

## 52-Week Level Rebalancing
- Hold positions until exit_rules trigger
- No daily rebalancing — let positions ride
- Stop loss is the only exit unless explicit exit signal

## Reporting
After rebalancing, broadcast knowledge to peers:
```bash
python tools/agent_comms.py --broadcast --intent strategy_insight \
  --data rebalance.json
```

This lets other agents know about your rotation in case it affects their trades.
