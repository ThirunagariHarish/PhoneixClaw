# Skill: Risk Management

## Purpose
Enforce strict risk controls on every trade and across the entire portfolio. Prevent catastrophic losses through position sizing rules, daily limits, and automatic mode switching.

## Pre-Trade Risk Checks

1. **Position Size**: proposed position must not exceed `max_position_size_pct` of portfolio value
2. **Concurrent Positions**: total open positions must not exceed `max_concurrent` for the active mode
3. **Daily Loss Limit**: if daily realised + unrealised loss exceeds `max_daily_loss_pct`, reject all new trades
4. **Duplicate Check**: do not open a second position in the same underlying if one already exists
5. **Pattern Requirement**: if `require_pattern_match` is true, at least `min_pattern_matches` rules must match with positive weight

## Position Sizing

Use fixed fractional sizing:
- Risk per trade = 1-2% of portfolio value
- Position size = risk_amount / (entry_price - stop_price)
- Never exceed `max_position_size_pct` regardless of calculation

## Automatic Mode Switching

- If daily loss reaches 50% of `daily_loss_limit`, automatically switch to conservative mode
- If daily P&L reaches `daily_pnl_cap`, stop trading for the day (capital preservation)
- Log mode switches and report to Phoenix

## Stop-Loss Rules

- Every trade MUST have a stop-loss placed immediately after fill
- Default stop: `stop_loss_pct` below entry for longs, above for shorts
- Trailing stop activates after position is up 10%: trail at 70% of max profit

## Daily Limits

| Metric | Conservative | Aggressive |
|--------|-------------|------------|
| P&L Target | $200 | $500 |
| Loss Limit | $100 | $200 |
| Max Positions | 2 | 5 |
| Confidence | 0.80 | 0.60 |
