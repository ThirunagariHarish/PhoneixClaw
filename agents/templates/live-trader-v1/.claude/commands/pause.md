Pause the live trading agent — stop taking new positions but continue monitoring.

1. Read `state.json` if it exists, or create it.

2. Set the paused flag:
   ```python
   import json
   from datetime import datetime, timezone

   state_file = "state.json"
   try:
       with open(state_file) as f:
           state = json.load(f)
   except (FileNotFoundError, json.JSONDecodeError):
       state = {}

   state["paused"] = True
   state["paused_at"] = datetime.now(timezone.utc).isoformat()
   state["pause_reason"] = "Manual pause via /pause command"

   with open(state_file, "w") as f:
       json.dump(state, f, indent=2)
   ```

3. Report the pause to Phoenix:
   ```
   python3 tools/report_to_phoenix.py --step pause --message "Agent paused by user" --progress 0
   ```

4. Confirm the action:
   ```
   === Agent PAUSED ===
   Time: {timestamp}
   Open Positions: {count} (these remain open — manage manually if needed)
   Discord Listener: Still running (monitoring only)

   The agent will continue monitoring Discord signals but will NOT execute any new trades.
   Use /resume-trading to resume trading.
   ```

5. List any open positions that may need manual attention.
