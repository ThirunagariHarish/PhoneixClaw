# Runbook: API Error Rate Spike (5xx)

**Alert:** `APIErrorRateHigh`  
**Severity:** Sev-2  
**Threshold:** 5xx rate > 1%  
**Owner:** DevOps

---

## Symptom

API is returning more than 1% of requests with 500-599 status codes, indicating server-side errors.

**User Impact:**
- Dashboard pages fail to load.
- API clients receive errors instead of data.
- User experience degraded.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
rate(http_requests_total{status="5xx"}[5m]) / rate(http_requests_total[5m])
```

If > 0.01 (1%), proceed to next step.

### 2. Identify Which Endpoints are Failing
```promql
rate(http_requests_total{status="5xx"}[5m]) by (endpoint)
```

**Action:** Isolate to specific route (e.g., `/api/v2/agents`, `/api/v2/trades`).

### 3. Check API Logs for Stack Traces
```bash
docker compose logs phoenix-api | grep -i "error\|exception\|traceback" | tail -n 50
```

Common error patterns:
- `IntegrityError: duplicate key` → DB constraint violation
- `TimeoutError: query timeout` → Slow query
- `ConnectionError: pool exhausted` → DB connection pool saturated
- `KeyError: 'field_name'` → Missing required field in request

### 4. Check Database Health
```sql
-- Active queries
SELECT pid, query, state, wait_event
FROM pg_stat_activity
WHERE state = 'active';

-- Blocked queries
SELECT blocked.pid AS blocked_pid, blocking.pid AS blocking_pid,
       blocked.query AS blocked_query, blocking.query AS blocking_query
FROM pg_stat_activity AS blocked
JOIN pg_stat_activity AS blocking ON blocking.pid = ANY(pg_blocking_pids(blocked.pid));
```

**Action:** If queries blocked, kill blocking PID or wait for transaction to complete.

### 5. Check API Process Health
```bash
# CPU / memory usage
docker stats phoenix-api

# Process count (should match WEB_CONCURRENCY)
docker compose exec phoenix-api ps aux | grep uvicorn
```

**Action:** If high CPU/memory, service is overloaded.

---

## Remediation

### Quick Fix (Temporary)
1. **Restart API service to clear stuck state:**
   ```bash
   docker compose restart phoenix-api
   ```

2. **Scale up API instances (if CPU-bound):**
   ```bash
   docker compose up -d --scale phoenix-api=3
   ```

3. **Kill long-running queries (if DB-bound):**
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'active' AND query_start < NOW() - INTERVAL '5 minutes';
   ```

### Permanent Fix

1. **If IntegrityError (duplicate key):**
   - Add unique constraint handling in route logic (catch exception, return 409 Conflict).
   - Use `INSERT ... ON CONFLICT DO NOTHING` for idempotent inserts.

2. **If TimeoutError (slow query):**
   - Add index to speed up query:
     ```sql
     CREATE INDEX idx_agent_trades_agent_id_created_at ON agent_trades(agent_id, created_at);
     ```
   - Increase query timeout (last resort):
     ```python
     # In config.py
     DB_QUERY_TIMEOUT = 30  # Up from 10
     ```

3. **If ConnectionError (pool exhausted):**
   - Increase DB connection pool size:
     ```python
     # In apps/api/src/config.py
     DB_POOL_SIZE = 20  # Up from 10
     ```
   - Add connection pool monitoring (see [db-pool-saturation.md](db-pool-saturation.md)).

4. **If KeyError (missing field):**
   - Add Pydantic validation to catch missing fields at API boundary:
     ```python
     from pydantic import BaseModel, Field

     class AgentCreate(BaseModel):
         name: str
         engine_type: str = Field(..., description="Required field")
     ```

5. **If high CPU/memory:**
   - Profile hot paths with `cProfile` or `py-spy`.
   - Cache expensive computations (Redis).
   - Offload heavy tasks to background workers.

---

## Escalation Path

1. **DevOps (primary)**: Restart service, check logs, scale up if needed.
2. **Eng Team (if code bug)**: Fix error handling, add validation, optimize queries.
3. **DBA (if DB issue)**: Kill queries, add indexes, tune pool settings.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add error tracking (Sentry, Rollbar) to capture stack traces automatically.
- [ ] Add integration test for error-prone endpoints (e.g., concurrent agent creation).
- [ ] Review error handling patterns (ensure all exceptions logged with request ID).
