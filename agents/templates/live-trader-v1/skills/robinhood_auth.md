# Robinhood Authentication Skill

## At startup
Before the first trade of the day, verify Robinhood connectivity:

```bash
# 1. Ensure HOME points to the agent's working dir so the session pickle
#    survives container restarts
export HOME=$PWD

# 2. Start the Robinhood MCP server and call robinhood_login
python tools/robinhood_mcp.py &  # runs in background on stdio
# Alternatively, the decision engine will auto-login on first use via _ensure_login()
```

## Credentials resolution order

The robinhood_mcp.py `_load_credentials()` helper tries these sources in order:

1. **Env vars:** `RH_USERNAME`, `RH_PASSWORD`, `RH_TOTP_SECRET`
2. **`ROBINHOOD_CONFIG`** env var pointing to a JSON file
3. **`./config.json`** in the agent's working directory
   - Looks under `robinhood_credentials` key first (Phoenix spawn format)
   - Falls back to `robinhood` key (alternate format)

Phoenix writes credentials to `config.json` under both `robinhood_credentials` and `robinhood` keys when you approve an agent, so option 3 should always work in production.

## Session persistence

`robin_stocks` stores its session pickle at `~/.tokens/robinhood.pickle`. Since the Docker container's default HOME is `/root` (ephemeral), we set `HOME` to the agent's working directory so the pickle goes into `data/live_agents/{id}/.tokens/robinhood.pickle`. This directory is persistent across container restarts, so you only need to enter TOTP on the FIRST login.

Your working directory has a pre-created `.tokens/` subdir — don't delete it.

## If authentication fails

1. Read the error carefully — common causes:
   - Bad password (check the connector credentials in the dashboard)
   - TOTP code rejected (the secret may be wrong, or the clock may be skewed)
   - Robinhood account locked / needs email verification
2. Report failure via `report_to_phoenix.py`:
   ```bash
   python tools/report_to_phoenix.py --event auth_failed --message "<specific error>"
   ```
3. **Automatically switch to paper mode** by updating the in-memory mode and setting `current_mode = "paper"` in `config.json`. Do NOT take live trades when auth is broken.
4. Notify the user via the notification dispatcher (this will trigger a WhatsApp alert)

## Testing the credentials manually

You can test the connector credentials via the API before depending on them:

```bash
curl -X POST https://cashflowus.com/api/v2/connectors/<connector-id>/test
```

Returns `{"success": true, "buying_power": 12345.67}` on success, or `{"success": false, "error": "..."}` on failure.

## Security notes

- Never log the password or TOTP secret
- Never commit `config.json` to git (it contains decrypted credentials at runtime)
- The `.tokens/robinhood.pickle` file contains session tokens — treat it as sensitive
- When the agent stops, the session pickle remains on disk for the next restart to reuse
