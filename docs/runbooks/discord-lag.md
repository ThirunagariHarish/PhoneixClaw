# Runbook: Discord Ingestion Lag

**Alert:** `DiscordIngestionLagHigh`  
**Severity:** Sev-2  
**Threshold:** p95 > 10s  
**Owner:** DevOps

---

## Symptom

Discord messages are taking more than 10 seconds (p95) to appear in the Phoenix database after being posted to the Discord channel.

**User Impact:**
- Signals are delayed, causing agents to miss optimal entry prices.
- Stale data may trigger trades at non-competitive prices.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
histogram_quantile(0.95, discord_ingestion_lag_seconds)
```

If > 10s, proceed to next step.

### 2. Verify Discord API Rate Limits
```bash
# Check message-ingestion logs for 429 errors
docker compose logs message-ingestion | grep -i "429\|rate limit"
```

**Action:** If rate-limited, back off polling frequency in `services/message-ingestion/src/main.py`.

### 3. Check Redis Stream Backlog
```bash
# Connect to Redis CLI
redis-cli

# Check stream length for all channels
XLEN stream:channel:1234567890
```

**Action:** If backlog > 1000 messages, consumer is falling behind. Check consumer logs.

### 4. Check Database Write Latency
```sql
-- In PostgreSQL
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
WHERE query LIKE '%discord_messages%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

**Action:** If write latency > 100ms, optimize query or add index.

### 5. Check Network Latency
```bash
# Ping Discord API
curl -w "@curl-format.txt" -o /dev/null -s https://discord.com/api/v10/gateway

# curl-format.txt:
# time_namelookup:  %{time_namelookup}\n
# time_connect:  %{time_connect}\n
# time_total:  %{time_total}\n
```

**Action:** If > 500ms, investigate network routing or Discord API status page.

---

## Remediation

### Quick Fix (Temporary)
1. Restart message-ingestion service to clear any stuck connections:
   ```bash
   docker compose restart message-ingestion
   ```

2. Increase worker concurrency (if CPU available):
   ```bash
   # In .env or docker-compose.yml
   MESSAGE_INGESTION_WORKERS=4  # Up from default 2
   docker compose up -d message-ingestion
   ```

### Permanent Fix
1. **If Discord rate-limited:**
   - Reduce polling frequency from 1s to 5s.
   - Implement exponential backoff on 429 responses.

2. **If Redis backlog:**
   - Scale up consumer instances (horizontal scaling).
   - Increase `XREAD` batch size to process more messages per call.

3. **If DB write slow:**
   - Add index on `discord_messages.timestamp`.
   - Batch inserts (insert 10 messages per transaction instead of 1).

4. **If network latency:**
   - Deploy message-ingestion service closer to Discord's region (US East).
   - Use HTTP/2 connection pooling.

---

## Escalation Path

1. **DevOps (primary)**: Restart service, check logs, adjust config.
2. **Eng Team (if code change needed)**: Optimize query, implement batching.
3. **DBA (if DB issue)**: Add indexes, tune query planner.
4. **Discord Support (if API outage)**: Check status.discord.com, file support ticket.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Update alert threshold if 10s is too sensitive.
- [ ] Add integration test for ingestion lag under load.
- [ ] Review Discord API usage patterns (consider webhooks vs polling).
