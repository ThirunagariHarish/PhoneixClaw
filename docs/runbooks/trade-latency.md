# Runbook: Signal-to-Trade Latency Spike

**Alert:** `SignalToTradeLatencyHigh`  
**Severity:** Sev-3  
**Threshold:** p95 > 5s  
**Owner:** Engineering

---

## Symptom

Signal-to-trade latency (time from signal XADD to `agent_trades` INSERT) is exceeding 5 seconds at p95, indicating a bottleneck in the pipeline.

**User Impact:**
- Trades executed at stale prices.
- Reduced profitability due to slippage.
- Competitive disadvantage vs other bots.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
histogram_quantile(0.95, signal_to_trade_latency_seconds)
```

If > 5s, proceed to next step.

### 2. Break Down Latency by Stage
```bash
# Check pipeline worker logs for per-stage timings
docker compose logs pipeline-worker | grep "TIMING"
```

Expected stages:
1. Signal deserialization (~1ms)
2. Enrichment (~50ms)
3. Inference (~100ms)
4. Risk check (~10ms)
5. Broker order (~200ms)
6. DB insert (~10ms)

**Action:** Identify which stage is slow.

### 3. Check Redis Stream Lag
```promql
histogram_quantile(0.95, redis_stream_lag_seconds)
```

**Action:** If > 1s, signals are piling up. Consumer is falling behind.

### 4. Check Database Query Latency
```sql
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
WHERE query LIKE '%agent_trades%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

**Action:** If > 100ms, optimize query or add index.

### 5. Check Broker API Latency
```bash
# Check broker adapter logs for HTTP round-trip times
docker compose logs phoenix-api | grep "broker_order_latency"
```

**Action:** If > 500ms, broker API is slow or network is congested.

---

## Remediation

### Quick Fix (Temporary)
1. **If enrichment slow:**
   - Reduce feature set (disable non-critical features in `enrich_single.py`).
   - Cache market data (avoid redundant API calls).

2. **If inference slow:**
   - Use smaller model (e.g., skip LSTM, use XGBoost only).
   - Pre-load model weights on startup (avoid lazy loading).

3. **If broker slow:**
   - Use limit orders instead of market orders (avoid slippage).
   - Increase timeout (if broker is reliable but occasionally slow).

### Permanent Fix

1. **If Redis consumer lag:**
   - Scale up pipeline-worker instances (horizontal scaling):
     ```bash
     docker compose up -d --scale pipeline-worker=3
     ```
   - Increase `XREAD` batch size to process more signals per call.

2. **If enrichment slow:**
   - Cache market data in Redis (TTL 60s):
     ```python
     cache_key = f"market_data:{ticker}"
     cached = redis.get(cache_key)
     if cached:
         return json.loads(cached)
     data = fetch_market_data(ticker)
     redis.setex(cache_key, 60, json.dumps(data))
     ```

3. **If inference slow:**
   - Move model inference to GPU (if available).
   - Use ONNX Runtime instead of native PyTorch (2-5x speedup).

4. **If broker slow:**
   - Switch to lower-latency broker (e.g., Robinhood typically faster than IBKR).
   - Use broker's batch order API (place multiple orders in one request).

5. **If DB slow:**
   - Add index on `agent_trades.entry_time`:
     ```sql
     CREATE INDEX idx_agent_trades_entry_time ON agent_trades(entry_time);
     ```
   - Use async DB driver (`asyncpg` instead of `psycopg2`).

---

## Escalation Path

1. **Eng Team (primary)**: Optimize enrichment/inference, cache market data.
2. **DevOps (if infra issue)**: Scale up workers, check network latency.
3. **DBA (if DB issue)**: Add indexes, tune query planner.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add per-stage latency metrics (enrichment, inference, broker, DB separately).
- [ ] Run benchmark test to verify fix: `python -m pytest tests/benchmark/test_signal_to_trade_latency.py`.
- [ ] Update target latency if 5s is unrealistic for current infrastructure.
