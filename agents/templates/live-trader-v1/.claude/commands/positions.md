Display all current open positions with live P&L.

1. Read `positions.json` if it exists.

2. For each open position show:
   - Ticker symbol
   - Direction (long/short)
   - Entry price and entry time
   - Current quantity / shares
   - Stop loss and take profit levels (if set)
   - Time held (duration since entry)
   - Unrealized P&L (if current price is available)

3. If the Robinhood MCP is available, fetch current prices:
   - For each position ticker, get the latest quote
   - Calculate unrealized P&L = (current_price - entry_price) * quantity
   - Calculate P&L percentage

4. Show a summary:
   ```
   === Open Positions ({count}) ===
   Ticker | Direction | Entry     | Qty  | Stop   | Target | Time Held | P&L
   -------|-----------|-----------|------|--------|--------|-----------|-----
   AAPL   | LONG      | $185.20   | 50   | $182   | $192   | 2h 15m    | +$120 (+1.3%)
   TSLA   | LONG      | $245.50   | 20   | $240   | $255   | 45m       | -$30 (-0.6%)

   Total Exposure: $12,350
   Total Unrealized P&L: +$90 (+0.7%)
   ```

5. If `positions.json` does not exist or is empty, report "No open positions."
