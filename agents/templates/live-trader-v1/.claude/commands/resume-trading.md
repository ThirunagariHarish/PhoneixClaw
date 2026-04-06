Resume live trading — re-enable position taking after a pause.

1. Read `state.json` to check current state.

2. If not currently paused, report: "Agent is already active — no action needed."

3. If paused, clear the flag:
   ```python
   import json
   from datetime import datetime, timezone

   state_file = "state.json"
   try:
       with open(state_file) as f:
           state = json.load(f)
   except (FileNotFoundError, json.JSONDecodeError):
       state = {}

   paused_at = state.get("paused_at", "unknown")
   state["paused"] = False
   state["resumed_at"] = datetime.now(timezone.utc).isoformat()
   del state["pause_reason"]

   with open(state_file, "w") as f:
       json.dump(state, f, indent=2)
   ```

4. Run a quick health check before resuming:
   - Is `config.json` valid?
   - Are risk parameters set?
   - Is the Discord listener running?
   - Check `positions.json` for current state

5. Report the resume to Phoenix:
   ```
   python3 tools/report_to_phoenix.py --step resume --message "Agent resumed by user" --progress 0
   ```

6. Confirm the action:
   ```
   === Agent RESUMED ===
   Time: {timestamp}
   Was paused since: {paused_at}
   Pause duration: {duration}
   Open Positions: {count}
   Risk Status: {ok/warning}

   The agent is now actively monitoring and will execute trades based on signals.
   ```
