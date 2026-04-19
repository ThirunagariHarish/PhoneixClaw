# Runbook: Database Connection Pool Saturation

**Alert:** `DBPoolSaturationHigh`  
**Severity:** Sev-1  
**Threshold:** Pool > 95% saturated  
**Owner:** DBA

---

## Symptom

Database connection pool is > 95% full, meaning almost all connections are in use. New requests will block or timeout waiting for a free connection.

**User Impact:**
- API requests timeout with 500 errors.
- Dashboard pages fail to load.
- Agents cannot write trades to DB.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
db_pool_connections{state="in_use"} / (db_pool_connections{state="in_use"} + db_pool_connections{state="idle"})
```

If > 0.95, proceed to next step.

### 2. Check Active Database Connections
```sql
SELECT count(*) AS active_connections
FROM pg_stat_activity
WHERE datname = 'phoenix_trade_bot';

-- Expected: < pool_size (default 10)
-- If >= pool_size, pool is saturated
```

### 3. Identify Long-Running Queries
```sql
SELECT pid, usename, query, state, NOW() - query_start AS duration
FROM pg_stat_activity
WHERE state = 'active'
  AND NOW() - query_start > INTERVAL '5 seconds'
ORDER BY duration DESC;
```

**Action:** If queries running > 30s, they may be holding connections too long.

### 4. Check for Connection Leaks
```bash
# Check API logs for unclosed connections
docker compose logs phoenix-api | grep -i "connection not closed\|leak"
```

**Action:** If connection not closed after request, leak exists.

### 5. Check Pool Configuration
```python
# In apps/api/src/config.py
print(f"DB_POOL_SIZE: {DB_POOL_SIZE}")  # Default 10
print(f"DB_MAX_OVERFLOW: {DB_MAX_OVERFLOW}")  # Default 5
```

**Action:** If pool too small for traffic, increase size.

---

## Remediation

### Quick Fix (Temporary)
1. **Kill idle connections to free pool slots:**
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle'
     AND NOW() - state_change > INTERVAL '10 minutes';
   ```

2. **Kill long-running queries:**
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'active'
     AND NOW() - query_start > INTERVAL '5 minutes';
   ```

3. **Restart API service to reset pool:**
   ```bash
   docker compose restart phoenix-api
   ```

### Permanent Fix

1. **Increase pool size (if traffic justified):**
   ```python
   # In apps/api/src/config.py
   DB_POOL_SIZE = 20  # Up from 10
   DB_MAX_OVERFLOW = 10  # Up from 5
   ```

   **Warning:** Ensure PostgreSQL `max_connections` can handle this:
   ```sql
   SHOW max_connections;  -- Should be >= pool_size * num_api_instances + 10
   ```

2. **Fix connection leaks:**
   - Ensure all DB sessions are closed in `finally` blocks:
     ```python
     try:
         db = SessionLocal()
         # ... use db
     finally:
         db.close()
     ```
   - Use FastAPI `Depends(get_db)` pattern (auto-closes after request).

3. **Add connection timeout:**
   ```python
   # In apps/api/src/config.py
   DB_POOL_TIMEOUT = 10  # Fail fast after 10s waiting for connection
   ```

4. **Optimize slow queries:**
   - Add indexes to reduce query time (see [api-errors.md](api-errors.md)).
   - Use query result caching (Redis) for read-heavy endpoints.

5. **Scale horizontally (if load too high):**
   - Deploy multiple API instances behind load balancer.
   - Each instance gets its own pool.

---

## Escalation Path

1. **DBA (primary)**: Kill queries, tune pool config, check PostgreSQL limits.
2. **DevOps (if infra issue)**: Scale up API instances, check network latency.
3. **Eng Team (if code issue)**: Fix connection leaks, optimize queries.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add connection pool monitoring to Grafana dashboard (gauge: in_use / total).
- [ ] Add alert for idle connections > 10 minutes (indicates leak).
- [ ] Review all DB session usage (ensure `finally: db.close()` everywhere).
- [ ] Run load test to verify pool size is sufficient for peak traffic.
