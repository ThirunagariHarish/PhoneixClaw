Show the current risk exposure and safety status of this live agent.

1. Read `config.json` for risk parameters:
   - max_position_size, max_portfolio_exposure, max_daily_loss
   - max_concurrent_positions, stop_loss_pct, take_profit_pct
   - Any other risk_params defined

2. Read `positions.json` to calculate current exposure:
   - Number of open positions vs max_concurrent_positions
   - Total portfolio exposure vs max_portfolio_exposure
   - Largest single position size vs max_position_size

3. Read `trades.log` for today's activity:
   - Total realized P&L today vs max_daily_loss
   - Number of trades today
   - Consecutive losses (current streak)

4. Run `python3 tools/risk_check.py` if available to get a live risk assessment.

5. Display a risk dashboard:
   ```
   === Risk Dashboard ===

   Position Limits:
     Open Positions:  2 / 5 max     [SAFE]
     Largest Position: $2,500 / $5,000 max  [SAFE]
     Total Exposure:  $4,800 / $20,000 max  [SAFE]

   Daily Limits:
     Realized P&L Today: -$150 / -$500 max  [WARNING: 30% of daily limit]
     Trades Today: 8

   Safety Checks:
     Stop Losses Set: 2/2 positions  [OK]
     Daily Loss Limit: 70% remaining [OK]
     Consecutive Losses: 2           [MONITOR]
   ```

6. Flag any limits that are >80% utilized as WARNING.
   Flag any limits that are exceeded as DANGER.
