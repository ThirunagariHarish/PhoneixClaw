Show the recent trade history from this live agent.

1. Read `trades.log` and parse the most recent 20 entries.

2. For each trade show:
   - Timestamp
   - Ticker
   - Action (BUY/SELL/CLOSE)
   - Price
   - Quantity
   - P&L (for closed trades)
   - Signal source (Discord message ID or auto-generated)
   - Reason / strategy that triggered the trade

3. Display in reverse chronological order (newest first):
   ```
   === Recent Trades (last 20) ===
   Time                | Ticker | Action | Price   | Qty | P&L      | Source
   --------------------|--------|--------|---------|-----|----------|--------
   2026-04-03 14:30:22 | AAPL   | SELL   | $186.50 | 50  | +$65.00  | Discord #12345
   2026-04-03 14:15:10 | AAPL   | BUY    | $185.20 | 50  | —        | Discord #12340
   ```

4. Show summary statistics for today's trades:
   - Total trades today
   - Wins vs losses
   - Total realized P&L
   - Win rate (today)
   - Largest win and largest loss

5. If `trades.log` does not exist or is empty, report "No trades recorded yet."
