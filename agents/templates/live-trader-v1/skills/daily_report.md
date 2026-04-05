# Skill: Daily Report

## Purpose
Generate end-of-day performance summary and report all metrics to the Phoenix dashboard.

## Trigger
Runs automatically at 4:05 PM ET (after market close).

## Report Contents

### Performance Summary
- Total trades taken today
- Winning / losing trades
- Total realised P&L
- Best and worst trade
- Win rate for the day

### Position Summary
- Open positions carried overnight (swing trades)
- Positions closed today with P&L breakdown
- Current portfolio value

### Decisions Log
- Total signals detected
- Signals accepted vs rejected
- Top 3 rejection reasons
- Average model confidence for accepted trades

### Risk Summary
- Max drawdown during the day
- Peak exposure (max concurrent positions)
- Any mode switches and triggers

## Reporting

1. Write structured summary to `daily_reports/YYYY-MM-DD.json`
2. POST summary to `{phoenix_api_url}/api/v2/agents/{agent_id}/metrics` with:
   - `portfolio_value`, `daily_pnl`, `total_trades`, `win_rate`
   - `signals_processed`, `signals_accepted`, `signals_rejected`
   - `avg_confidence`, `max_drawdown`
3. Send heartbeat with `status: "day_complete"`
