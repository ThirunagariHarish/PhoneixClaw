# OpenClaw Agent Logs & Error Capture

## Capturing agent activity and errors

1. **Error log API** — Any client (dashboard, bridge, cron) can POST to:
   - `POST /api/v2/error-logs` with `source: "openclaw_agent"` and `component: "<agent_id>"` to record agent errors or activity.
   - `POST /api/v2/error-logs/ingest-agent-activity` with body:
     ```json
     { "instance_id": "optional-id", "logs": [ { "message": "...", "component": "agent-id", "severity": "error" } ] }
     ```
   This creates error log entries with `source=openclaw_agent` so they appear on the Dev Sprint Board and can be filtered.

2. **Bridge integration** — Your OpenClaw bridge can call the Phoenix API (with auth) to submit agent logs. Example:
   ```bash
   curl -X POST "$PHOENIX_API_URL/api/v2/error-logs/ingest-agent-activity" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"instance_id":"bridge-1","logs":[{"message":"Agent X failed","component":"agent-x","severity":"error"}]}'
   ```

3. **Dev Sprint Board** — Admins can filter by `source=openclaw_agent` to see only agent-originated logs and track fixes.
