Show the current state of this live trading agent.

1. Read `config.json` for agent identity:
   - agent_id, channel_name, analyst_name
   - Current modes (aggressive, conservative, etc.)
   - Risk parameters

2. Check `state.json` if it exists:
   - Is the agent paused?
   - Last activity timestamp
   - Current operating mode

3. Read `positions.json` to count open positions:
   - Number of open positions
   - Total exposure (sum of position values)

4. Read the last 5 entries from `trades.log` for recent activity.

5. Check if the Discord listener is running:
   - Look for `tools/discord_listener.py` process or PID file

6. Report heartbeat status:
   - Run: `python3 tools/report_to_phoenix.py --event heartbeat`

Display a formatted status dashboard:
```
=== Phoenix Live Agent Status ===
Agent: {agent_id} | Channel: {channel_name} | Analyst: {analyst_name}
Mode: {mode} | Paused: {yes/no}
Open Positions: {count} | Total Exposure: ${amount}
Last Trade: {time} | Last Signal: {time}
Discord Listener: {running/stopped}
```
