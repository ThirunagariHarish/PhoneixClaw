# Runbook: Redis Stream Lag

**Alert:** `RedisStreamLagHigh`  
**Severity:** Sev-2  
**Threshold:** p95 > 5s  
**Owner:** DevOps

---

## Symptom

Messages in Redis Streams are taking more than 5 seconds (p95) to be consumed after being published (XADD → XREAD lag).

**User Impact:**
- Signals are delayed, causing stale trades.
- Real-time updates (agent logs, trade feed) are not real-time.
- Dashboard SSE stream lags behind actual events.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
histogram_quantile(0.95, redis_stream_lag_seconds)
```

If > 5s, proceed to next step.

### 2. Check Stream Backlog
```bash
redis-cli

# Check length of each stream
XLEN stream:channel:1234567890
XLEN stream:trades
XLEN stream:agent_logs

# Expected: < 100 messages
# If > 1000, consumer is falling behind
```

### 3. Check Consumer Group Info
```bash
redis-cli

# Get consumer group details
XINFO GROUPS stream:channel:1234567890

# Check pending messages
XPENDING stream:channel:1234567890 consumer_group
```

**Action:** If pending count high, consumer is processing too slowly.

### 4. Check Consumer Logs
```bash
# Check pipeline-worker or message-ingestion consumer logs
docker compose logs pipeline-worker | grep -i "redis\|stream\|XREAD"
```

Common patterns:
- `ConnectionError: Redis connection timeout`
- `ResponseError: BUSYGROUP Consumer Group already exists`
- Slow processing loop (> 1s per message)

### 5. Check Redis Server Health
```bash
redis-cli INFO

# Key metrics:
# - used_memory_human (should be < 90% of maxmemory)
# - connected_clients (should be < maxclients)
# - evicted_keys (should be 0)
```

**Action:** If memory > 90%, Redis is evicting keys.

---

## Remediation

### Quick Fix (Temporary)
1. **Restart consumer to reset stuck state:**
   ```bash
   docker compose restart pipeline-worker
   docker compose restart message-ingestion
   ```

2. **Trim old messages from stream:**
   ```bash
   redis-cli

   # Keep only last 1000 messages
   XTRIM stream:channel:1234567890 MAXLEN ~ 1000
   ```

3. **Increase consumer parallelism:**
   ```bash
   # Scale up consumer instances
   docker compose up -d --scale pipeline-worker=3
   ```

### Permanent Fix

1. **If consumer too slow:**
   - Profile consumer code (cProfile, py-spy) to find bottleneck.
   - Batch processing: read 100 messages per XREAD instead of 1:
     ```python
     messages = redis.xread({'stream:key': last_id}, count=100)
     ```
   - Increase `XREAD` timeout to allow larger batches.

2. **If Redis memory full:**
   - Increase maxmemory:
     ```bash
     # In redis.conf or docker-compose.yml
     maxmemory 2gb  # Up from 1gb
     ```
   - Enable eviction policy (LRU):
     ```bash
     maxmemory-policy allkeys-lru
     ```

3. **If network latency:**
   - Deploy consumer closer to Redis (same datacenter).
   - Use Redis connection pooling to reduce connection overhead.

4. **If message throughput too high:**
   - Shard streams by key (e.g., one stream per channel instead of global stream).
   - Use Redis Cluster for horizontal scaling.

5. **If consumer crash loop:**
   - Add error handling to prevent poison messages from blocking the stream:
     ```python
     try:
         process_message(msg)
     except Exception as e:
         logger.error(f"Failed to process {msg['id']}: {e}")
         # XACK anyway to avoid blocking stream
         redis.xack(stream_key, group, msg['id'])
     ```

---

## Escalation Path

1. **DevOps (primary)**: Restart consumers, check Redis health, scale up instances.
2. **Eng Team (if code issue)**: Optimize consumer loop, add batching, fix crash loop.
3. **Redis Support (if server issue)**: Check Redis Cloud / AWS ElastiCache status.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add stream backlog monitoring to Grafana (XLEN for each stream).
- [ ] Add consumer processing rate metric (messages/sec).
- [ ] Set up auto-trimming for streams (MAXLEN 10000 on all XADDs).
- [ ] Run load test to verify consumer can handle peak throughput (1000 msgs/sec).
