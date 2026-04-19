# Runbook: Broker Order Failure

**Alert:** `BrokerOrderFailureRateHigh`  
**Severity:** Sev-2  
**Threshold:** Failure rate > 5%  
**Owner:** Engineering

---

## Symptom

More than 5% of broker order requests (Robinhood MCP or IBKR Gateway) are failing with `rejected`, `timeout`, or other non-filled status.

**User Impact:**
- Agents cannot execute trades.
- Paper-mode agents unaffected, but live agents stuck.
- PnL tracking incomplete.

---

## Diagnostic Steps

### 1. Check Prometheus Metric
```promql
rate(broker_order_total{status!="filled"}[5m]) / rate(broker_order_total[5m])
```

If > 0.05, proceed to next step.

### 2. Check Which Broker is Failing
```promql
broker_order_total{status="rejected"}
# Group by broker label
```

**Action:** Isolate to Robinhood or IBKR.

### 3. Check Broker API Logs
```bash
# Robinhood MCP server logs
docker compose logs robinhood-mcp | grep -i "error\|rejected\|timeout"

# IBKR Gateway logs (if applicable)
cat /var/log/ibkr_gateway.log | tail -n 100
```

Common error patterns:
- `401 Unauthorized` → Credentials expired
- `429 Too Many Requests` → Rate limited
- `503 Service Unavailable` → Broker API outage
- `INVALID_SYMBOL` → Ticker not supported

### 4. Check Circuit Breaker State
```promql
circuit_breaker_state{broker="robinhood"}
# 0 = CLOSED (healthy)
# 1 = HALF_OPEN (testing)
# 2 = OPEN (failing)
```

**Action:** If OPEN, breaker is protecting against sustained failures. Root cause must be fixed before breaker resets.

### 5. Test Broker Connection Manually
```bash
# Robinhood MCP test
curl -X POST http://localhost:8012/mcp/get_account \
  -H "Content-Type: application/json" \
  -d '{"username": "...", "password": "..."}'

# IBKR test (via ib_insync)
python3 -c "
from ib_insync import IB
ib = IB()
ib.connect('localhost', 4001, clientId=1)
print(ib.accountValues())
ib.disconnect()
"
```

**Action:** If fails, credentials or gateway connection is broken.

---

## Remediation

### Quick Fix (Temporary)
1. **If credentials expired (Robinhood):**
   - Re-authenticate via Robinhood app (approve new device).
   - Update session pickle:
     ```bash
     # Restart agent to trigger fresh login
     docker compose restart phoenix-api
     ```

2. **If credentials expired (IBKR):**
   - Restart IB Gateway and re-enter credentials via TWS.
   - Update `IB_GATEWAY_HOST` if IP changed.

3. **If rate-limited:**
   - Reduce order frequency (add delay between orders).
   - Wait 5-10 minutes for rate limit to reset.

### Permanent Fix

1. **If Robinhood session revocation loop:**
   - Verify session pickle is persisted to agent working directory (not `/tmp`).
   - Ensure `HOME` env var points to persistent directory.
   - Check `apps/api/src/services/robinhood_context_fetcher.py` does NOT call `logout()`.

2. **If IBKR daily re-auth required:**
   - Schedule cron job to restart IB Gateway at 5 AM ET:
     ```bash
     0 5 * * * systemctl restart ibkr-gateway
     ```

3. **If broker API outage:**
   - Monitor status pages:
     - Robinhood: https://status.robinhood.com
     - IBKR: https://ibkr.com/status
   - Wait for resolution; circuit breaker will auto-reset when broker recovers.

4. **If invalid symbols:**
   - Add symbol validation before order placement.
   - Maintain allowlist of tradable symbols per broker.

---

## Escalation Path

1. **Eng Team (primary)**: Fix adapter logic, credentials handling, session persistence.
2. **DevOps (if infra issue)**: Restart gateway, check network connectivity.
3. **Broker Support (if API outage)**: File support ticket with Robinhood/IBKR.

---

## Post-Incident

- [ ] Document root cause in post-mortem.
- [ ] Add pre-flight symbol validation (reject invalid tickers before broker call).
- [ ] Improve credential refresh flow (auto-refresh before expiration).
- [ ] Add integration test for broker adapter under simulated failures (401, 429, 503).
