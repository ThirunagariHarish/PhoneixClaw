Calculate and display comprehensive performance metrics for this live agent.

1. Read `trades.log` and parse all completed (closed) trades.

2. Calculate overall performance metrics:
   - Total trades taken
   - Win rate (% profitable)
   - Total realized P&L (dollar and percentage)
   - Average win size vs average loss size
   - Profit factor (gross profits / gross losses)
   - Largest win and largest loss
   - Average holding time
   - Maximum consecutive wins and losses

3. Calculate risk-adjusted metrics:
   - Sharpe ratio (if enough data points)
   - Max drawdown (peak-to-trough)
   - Recovery factor (total P&L / max drawdown)
   - Calmar ratio (annual return / max drawdown)

4. Break down by time period:
   - Today's performance
   - This week's performance
   - All-time performance

5. Break down by ticker:
   - Which tickers are most profitable
   - Which tickers have highest win rate
   - Which tickers to avoid (negative P&L)

6. Display formatted:
   ```
   === Performance Report ===

   Overall: 45 trades | 64.4% win rate | +$1,250 total P&L
   Profit Factor: 1.82 | Sharpe: 1.34 | Max Drawdown: -$380

   By Period:
     Today:     5 trades | 80% WR | +$220
     This Week: 18 trades | 66.7% WR | +$580
     All-time:  45 trades | 64.4% WR | +$1,250

   Top Tickers:
     AAPL:  12 trades | 75% WR | +$450
     TSLA:   8 trades | 62% WR | +$280
     SPY:   10 trades | 50% WR | -$50
   ```

7. If no trades exist, report "No completed trades yet."
