# Runbook: Agent Wake Failure

**Alert:** `AgentWakeFailureRateHigh`  
**Severity:** Sev-1  
**Threshold:** Failure rate > 10%  
**Owner:** Engineering

---

## Symptom

More than 10% of agent spawn requests are failing, resulting in agents stuck in `ERROR` state instead of `RUNNING`.

**User Impact:**
- New agents cannot be created.
- Existing agents fail to wake after pause/resume.
- Live trading interrupted.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
rate(agent_wake_total{status="failure"}[5m]) / rate(agent_wake_total[5m])
```

If > 0.10, proceed to next step.

### 2. Check API Logs for Errors
```bash
docker compose logs phoenix-api | grep -i "agent_gateway\|agent spawn\|ERROR"
```

Common error patterns:
- `FileNotFoundError: CLAUDE.md template not found`
- `PermissionError: Cannot write to agent working directory`
- `subprocess.CalledProcessError: Agent process exited with code 1`

### 3. Check Agent Working Directory Permissions
```bash
# Verify base directory exists and is writable
ls -la agents/
# Expected: drwxr-xr-x (755 or 775)

# Check disk space
df -h /var/lib/docker  # or wherever agents/ is mounted
```

**Action:** If permissions wrong, fix with `chmod -R 755 agents/`.

### 4. Check Database for Failed Agents
```sql
SELECT id, name, status, error_message, created_at
FROM agents
WHERE status = 'ERROR'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;
```

**Action:** Review `error_message` for clues (e.g., missing connector, invalid config).

### 5. Test Agent Spawn Manually
```bash
# Try spawning an agent via API
curl -X POST http://localhost:8011/api/v2/agents \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Wake",
    "type": "trading",
    "connector_id": "valid_connector_id",
    "engine_type": "pipeline"
  }'
```

**Action:** If fails, review response body for specific error.

---

## Remediation

### Quick Fix (Temporary)
1. Restart API service to clear any in-memory state corruption:
   ```bash
   docker compose restart phoenix-api
   ```

2. Clear failed agent sessions:
   ```sql
   DELETE FROM agent_sessions WHERE status = 'ERROR';
   ```

### Permanent Fix

1. **If FileNotFoundError:**
   - Verify `agents/templates/live-trader-v1/CLAUDE.md` exists.
   - Check template path in `apps/api/src/services/agent_gateway.py`.

2. **If PermissionError:**
   - Ensure Docker volume mount has correct permissions.
   - Check SELinux/AppArmor policies (if applicable).

3. **If subprocess exit code 1:**
   - Agent process crashed on startup. Check agent logs:
     ```bash
     cat agents/<agent_id>/.logs/agent.log
     ```
   - Common causes: missing Python dependency, invalid config.json, broker auth failure.

4. **If connector missing:**
   - Verify connector exists in DB:
     ```sql
     SELECT id, name, type FROM connectors WHERE id = 'connector_id';
     ```
   - If missing, create connector before agent.

---

## Escalation Path

1. **Eng Team (primary)**: Review agent_gateway.py, fix template or subprocess logic.
2. **DevOps (if infra issue)**: Fix permissions, check Docker volume mounts.
3. **DBA (if DB constraint issue)**: Review foreign key violations, fix schema.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add pre-flight validation to agent creation API (check connector exists, template readable).
- [ ] Improve error messages (include agent_id and specific failure reason).
- [ ] Add integration test for agent spawn under load (100 concurrent requests).
