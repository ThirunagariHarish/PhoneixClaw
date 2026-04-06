Generate a formatted daily performance report and send it to Phoenix.

1. Gather today's data:
   - Read `trades.log` for today's trades
   - Read `positions.json` for current open positions
   - Read `config.json` for agent identity

2. Calculate daily metrics:
   - Trades executed today (count, win/loss breakdown)
   - Signals received vs acted on
   - Total realized P&L for the day
   - Current unrealized P&L from open positions
   - Best and worst trade of the day
   - Risk utilization (% of daily loss limit used)

3. Generate the report:
   ```
   ══════════════════════════════════════
   DAILY REPORT — {date}
   Agent: {channel_name} | Analyst: {analyst_name}
   ══════════════════════════════════════

   SUMMARY
   Trades: {count} | Wins: {wins} | Losses: {losses} | Win Rate: {wr}%
   Realized P&L: ${pnl} | Unrealized: ${upnl}

   TRADES
   {list of today's trades with details}

   OPEN POSITIONS
   {list of current positions}

   RISK STATUS
   Daily Loss Used: {pct}% | Positions: {n}/{max}

   NOTES
   {any notable events, errors, or observations}
   ══════════════════════════════════════
   ```

4. Send the report to Phoenix:
   ```python
   python3 tools/report_to_phoenix.py --step daily_report --message "Daily report generated" --progress 0
   ```

5. Save the report to `reports/daily_{date}.txt` for archival.
