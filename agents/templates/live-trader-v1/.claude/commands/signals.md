Show recent Discord signals detected by the agent and their disposition.

1. Read `signals.log` or `trades.log` for signal entries.

2. Also check if `tools/discord_redis_consumer.py` has recent output or state files (check `stream_cursor.json` and `pending_signals.json`).

3. For each recent signal (last 20), show:
   - Timestamp
   - Discord message content (truncated to 100 chars)
   - Parsed ticker and direction
   - Confidence score (from the model)
   - Action taken: EXECUTED / FILTERED / IGNORED
   - Filter reason (if filtered): risk limit, low confidence, duplicate, paused, etc.

4. Display:
   ```
   === Recent Signals (last 20) ===
   Time       | Message                    | Ticker | Confidence | Action
   -----------|----------------------------|--------|------------|--------
   14:30:22   | "AAPL calls looking g..."  | AAPL   | 0.87       | EXECUTED
   14:25:10   | "SPY puts, market wea..."  | SPY    | 0.45       | FILTERED (low confidence)
   14:20:05   | "Good morning everyone..." | —      | —          | IGNORED (no signal)
   ```

5. Show signal statistics:
   - Total signals detected today
   - Signals executed vs filtered vs ignored
   - Average confidence of executed signals
   - Most common filter reason

6. If no signal data is found, explain that the Discord listener may not be running
   and suggest: `python3 tools/discord_redis_consumer.py --config config.json --output pending_signals.json`
