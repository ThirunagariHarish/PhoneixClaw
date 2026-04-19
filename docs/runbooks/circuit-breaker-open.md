# Runbook: Circuit Breaker Open

**Alert:** `CircuitBreakerOpen`  
**Severity:** Sev-2  
**Threshold:** OPEN state > 5 minutes  
**Owner:** DevOps

---

## Symptom

Circuit breaker for a broker adapter (Robinhood or IBKR) is stuck in OPEN state, meaning the adapter is refusing all order requests to prevent cascading failures.

**User Impact:**
- All orders to the affected broker are blocked.
- Agents cannot execute trades.
- Live trading halted until breaker resets.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
circuit_breaker_state{broker="robinhood"}
# 2 = OPEN (failing)
```

If OPEN for > 5 minutes, proceed to next step.

### 2. Check Broker Adapter Logs
```bash
docker compose logs phoenix-api | grep -i "circuit breaker\|broker\|OPEN"
```

Common patterns:
- `CircuitBreaker OPEN: 10 consecutive failures`
- `Broker API returned 503 Service Unavailable`
- `Timeout after 10s waiting for broker response`

### 3. Check Broker API Status
- **Robinhood:** https://status.robinhood.com
- **IBKR:** https://ibkr.com/status

**Action:** If outage confirmed, wait for broker to recover. Breaker will auto-reset when healthy.

### 4. Test Broker Connectivity Manually
```bash
# Robinhood MCP test
curl -X POST http://localhost:8012/mcp/get_account \
  -H "Content-Type: application/json" \
  -d '{"username": "...", "password": "..."}'

# IBKR test
python3 -c "
from ib_insync import IB
ib = IB()
ib.connect('localhost', 4001, clientId=1)
print(ib.reqCurrentTime())
ib.disconnect()
"
```

**Action:** If fails, root cause is connectivity or auth.

### 5. Check Failure History
```sql
-- Query agent_trades for recent broker failures
SELECT broker_order_id, status, rejection_reason, created_at
FROM agent_trades
WHERE status IN ('rejected', 'error')
  AND created_at > NOW() - INTERVAL '10 minutes'
ORDER BY created_at DESC
LIMIT 20;
```

**Action:** Review `rejection_reason` for patterns (e.g., all 503, all timeout).

---

## Remediation

### Quick Fix (Temporary)
1. **Force breaker reset (use with caution):**
   ```python
   # In agent_gateway.py or broker adapter
   circuit_breaker.reset()  # Manually close the breaker
   ```

   **Warning:** Only do this if root cause is fixed (e.g., broker recovered from outage).

2. **Switch to fallback broker:**
   - If Robinhood down, temporarily route orders to IBKR.
   - Update agent config to use alternate broker.

### Permanent Fix

1. **If broker API outage:**
   - Wait for broker to recover.
   - Breaker will auto-reset after `recovery_timeout` (default 60s) once broker responds successfully.

2. **If timeout too aggressive:**
   - Increase broker request timeout from 10s to 30s:
     ```python
     # In broker adapter
     timeout = 30.0  # Up from 10.0
     ```

3. **If credential expired:**
   - Re-authenticate with broker (see [broker-order-failure.md](broker-order-failure.md)).
   - Breaker will reset once auth succeeds.

4. **If network congestion:**
   - Check DNS resolution, firewall rules, proxy settings.
   - Use traceroute to broker API endpoint.

5. **If breaker misconfigured:**
   - Review failure threshold:
     ```python
     # In circuit_breaker.py
     failure_threshold = 10  # Trip after 10 consecutive failures
     recovery_timeout = 60   # Test recovery after 60s
     ```
   - Adjust if too sensitive for intermittent broker slowness.

---

## Escalation Path

1. **DevOps (primary)**: Check broker status, test connectivity, force reset if safe.
2. **Eng Team (if code issue)**: Review breaker config, adjust thresholds.
3. **Broker Support (if API outage)**: File support ticket with Robinhood/IBKR.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add circuit breaker state to Grafana dashboard (gauge showing CLOSED/HALF_OPEN/OPEN).
- [ ] Add integration test for breaker behavior under sustained broker failures.
- [ ] Review failure threshold (10 consecutive failures may be too low).
