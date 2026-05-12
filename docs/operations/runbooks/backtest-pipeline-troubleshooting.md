# Runbook: Backtest Pipeline Troubleshooting

**Owner:** Platform Team  
**Severity:** Sev-2 (impacts new agent onboarding)  
**Related Docs:**
- [Feature Store & Worker-Pod Architecture](../../architecture/feature-store-and-worker-pod-2026-05-12.md)
- [ADR 0007: Feature Store and Out-of-Process Backtest](../../architecture/adrs/0007-feature-store-and-out-of-process-backtest.md)
- [Feature Store Setup Runbook](../feature-store-runbook.md)

---

## Overview

This runbook covers common backtest pipeline failures and how to diagnose/fix them. The new architecture (as of 2026-05-12) uses a feature store, out-of-process worker, and Redis stream queue. Most issues fall into one of five categories:

1. Backtest stuck at "Feature: enrich" step
2. Worker pod is down or crashlooping
3. Feature store is empty or stale
4. Redis stream backlog growing
5. Tiingo API key expired or rate-limited

---

## 1. Backtest Stuck at "Feature: enrich"

### Symptom

Dashboard shows a backtest in `RUNNING` state with progress bar stuck at "Feature: enrich [45/500, 9%]" for >10 minutes.

### Diagnostic Steps

#### 1.1 Check worker pod logs

```bash
kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=200 -f | grep -A5 "enrich"
```

**Look for:**
- `TiingoProvider: rate limit hit (429)` → Go to §5 (Tiingo API issues)
- `MarketDataProvider: falling back to yfinance` → yfinance is slower; expected if Tiingo is down
- `yfinance.exceptions.YFinanceError: No data found` → Ticker is delisted or invalid
- `asyncio.TimeoutError` → Network issue or API timeout

#### 1.2 Query feature-store coverage

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT
    COUNT(DISTINCT pt.id) AS total_parsed_trades,
    COUNT(DISTINCT et.parsed_trade_id) AS enriched_count,
    ROUND(100.0 * COUNT(DISTINCT et.parsed_trade_id) / NULLIF(COUNT(DISTINCT pt.id), 0), 2) AS coverage_pct
FROM parsed_trades pt
LEFT JOIN enriched_trades et ON et.parsed_trade_id = pt.id AND et.computed_version = 'v1'
WHERE pt.created_at >= NOW() - INTERVAL '90 days';
"
```

**Expected:** coverage_pct > 90%  
**Action:** If < 50%, the feature store is missing data → see §3

#### 1.3 Check backtest step logs

```bash
# Get backtest_id from dashboard URL or API
BACKTEST_ID="<uuid>"

kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT step, sub_progress_pct, message, ts
FROM agent_backtest_step_logs
WHERE backtest_id = '$BACKTEST_ID'
ORDER BY ts DESC
LIMIT 20;
"
```

**Look for:**
- Last message timestamp > 5 minutes ago → worker may be hung
- Repeated errors on same ticker (e.g., "AAPL: 429 rate limit") → Tiingo issue

### Fix

#### If feature store is empty (< 50% coverage)

1. Manually trigger feature-extraction CronJob:
   ```bash
   kubectl create job --from=cronjob/feature-extraction manual-fe-$(date +%s) -n phoenix
   ```

2. Wait for job to complete (~10-15 min for 500 trades):
   ```bash
   kubectl logs -n phoenix job/manual-fe-<timestamp> -f
   ```

3. Re-enqueue the backtest:
   ```bash
   kubectl exec -n phoenix deploy/phoenix-api -- python3 -c "
   import asyncio
   from shared.messaging.backtest_requests import enqueue_backtest
   # Get backtest config from DB first
   asyncio.run(enqueue_backtest('$BACKTEST_ID', '<agent-id>', {...}))
   "
   ```

#### If Tiingo is rate-limited (429 errors)

1. Check Tiingo rate limit status:
   ```bash
   curl -H "Authorization: Token $TIINGO_API_KEY" \
     https://api.tiingo.com/api/test | jq
   ```

2. If rate limit hit (1000 req/hour on free tier):
   - **Option A:** Wait 1 hour for reset
   - **Option B:** Rotate to backup Tiingo API key (if available)
   - **Option C:** Accept yfinance fallback (slower but completes)

#### If worker is hung (last log > 5 min ago)

1. Restart the worker pod:
   ```bash
   kubectl rollout restart deployment/phoenix-backtest-worker -n phoenix
   kubectl rollout status deployment/phoenix-backtest-worker -n phoenix
   ```

2. Worker auto-resumes from Redis stream (XREADGROUP picks up unconsumed entries)

### Verification

```bash
# Check backtest status
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT id, status, current_step, progress_pct, updated_at
FROM agent_backtests
WHERE id = '$BACKTEST_ID';
"

# Expected: status='COMPLETED' within 5 min
```

---

## 2. Worker Pod is Down

### Symptom

```bash
kubectl get pods -n phoenix | grep backtest-worker
# phoenix-backtest-worker-abc123-xyz  0/1  CrashLoopBackOff  5  10m
```

Dashboard shows new backtests stuck in `QUEUED` state (never transition to `RUNNING`).

### Diagnostic Steps

#### 2.1 Check pod status and events

```bash
kubectl describe pod -n phoenix -l app.kubernetes.io/component=phoenix-backtest-worker | tail -50
```

**Common failure modes:**
- `ImagePullBackOff` → CD pipeline failed to push image
- `CrashLoopBackOff` → Application startup error (missing env var, DB connection failure)
- `OOMKilled` → Memory limit (4Gi) exceeded during training

#### 2.2 Check pod logs

```bash
kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=100
```

**Look for:**
- `redis.exceptions.ConnectionError` → Redis is down
- `asyncpg.exceptions.CannotConnectNowError` → Postgres is unavailable
- `FileNotFoundError: [Errno 2] No such file or directory: '/var/lib/phoenix/backtests'` → PVC mount failed

#### 2.3 Check PVC mounts

```bash
kubectl get pvc -n phoenix | grep -E "phoenix-price-cache|phoenix-backtest-data"

# Expected output:
# phoenix-price-cache     Bound  pvc-abc123  5Gi   RWO  ...
# phoenix-backtest-data   Bound  pvc-xyz789  20Gi  RWO  ...
```

**Action:** If PVC is `Pending`, node may lack disk space or PV provisioner is down.

#### 2.4 Check Redis stream depth

```bash
kubectl exec -n phoenix redis-0 -- redis-cli XLEN backtest:requests
# Expected: 0-2 (normal), 10+ (worker is down and backlog is growing)
```

```bash
kubectl exec -n phoenix redis-0 -- redis-cli XPENDING backtest:requests backtest-workers - + 10
# Shows pending (unconsumed) entries
```

### Fix

#### If OOMKilled

1. Check memory usage during training:
   ```bash
   kubectl top pod -n phoenix -l app.kubernetes.io/component=phoenix-backtest-worker
   # If memory near 4Gi limit, increase to 6Gi
   ```

2. Edit Helm values:
   ```yaml
   # helm/phoenix/values.yaml
   resources:
     backtestWorker:
       memory: 6Gi
   ```

3. Upgrade Helm release:
   ```bash
   helm upgrade phoenix helm/phoenix -n phoenix --wait
   ```

#### If missing env var (e.g., TIINGO_API_KEY)

1. Check secrets:
   ```bash
   kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.TIINGO_API_KEY}' | base64 -d
   # If empty, add via kubeseal
   ```

2. Seal secret:
   ```bash
   kubectl create secret generic phoenix-secrets-new \
     --from-literal=TIINGO_API_KEY=<new-key> \
     --dry-run=client -o yaml | \
     kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system -o yaml > sealed-secret.yaml

   kubectl apply -f sealed-secret.yaml -n phoenix
   ```

3. Restart worker:
   ```bash
   kubectl rollout restart deployment/phoenix-backtest-worker -n phoenix
   ```

#### If Redis is down

1. Check Redis pod:
   ```bash
   kubectl get pods -n phoenix | grep redis
   kubectl logs -n phoenix redis-0 --tail=100
   ```

2. If Redis is crashlooping, check disk space:
   ```bash
   kubectl exec -n phoenix redis-0 -- df -h /data
   ```

3. Restart Redis:
   ```bash
   kubectl rollout restart deployment/redis -n phoenix
   ```

### Verification

```bash
# Worker pod is running
kubectl get pods -n phoenix | grep backtest-worker
# Expected: 1/1 Running

# Redis stream is being consumed
kubectl exec -n phoenix redis-0 -- redis-cli XLEN backtest:requests
# Expected: 0 (all entries processed)

# New backtests transition from QUEUED → RUNNING within 10s
```

---

## 3. Feature Store is Empty

### Symptom

All backtests are slow (10-15 min instead of <2 min). Dashboard shows "Feature: enrich" step taking >5 min for 500 trades.

Worker logs show:
```
enrich.py: feature store miss for trade 1/500 (parsed_trade_id=abc-123)
enrich.py: falling back to inline enrichment via MarketDataProvider
```

### Diagnostic Steps

#### 3.1 Check feature store row count

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT COUNT(*) AS enriched_rows FROM enriched_trades;
"

# Expected: >1000 rows for a production system with 500+ parsed_trades
# Actual: 0 or <100 rows → feature store is empty or stale
```

#### 3.2 Check feature-extraction CronJob status

```bash
kubectl get cronjobs -n phoenix | grep feature-extraction

# Expected: feature-extraction  0 3 * * *  ...  3 successful, 0 failed
```

```bash
kubectl get jobs -n phoenix | grep feature-extraction | head -5

# Check last 3 runs
kubectl logs -n phoenix job/feature-extraction-<timestamp> --tail=100
```

**Look for:**
- Job succeeded but no rows inserted → CronJob is running but feature logic is broken
- Job failed with `TiingoProvider: 401 Unauthorized` → API key missing or expired
- Job never ran → CronJob schedule is incorrect or suspended

#### 3.3 Check daily_bars table

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT COUNT(*) AS total_bars, MIN(date) AS earliest, MAX(date) AS latest
FROM daily_bars;
"

# Expected: >10000 rows spanning 5 years
# If 0 rows, backfill script was never run
```

### Fix

#### If daily_bars is empty

1. Run backfill script (one-time):
   ```bash
   # From repo root on your Mac
   python scripts/backfill_daily_bars.py --years 5

   # Or via kubectl exec into phoenix-api pod
   kubectl exec -it -n phoenix deploy/phoenix-api -- bash
   cd /app
   python scripts/backfill_daily_bars.py --years 5
   ```

   This takes ~30 minutes for 5 years × 60 tickers.

#### If enriched_trades is empty

1. Manually trigger feature-extraction CronJob:
   ```bash
   kubectl create job --from=cronjob/feature-extraction manual-fe-$(date +%s) -n phoenix
   ```

2. Monitor job logs:
   ```bash
   kubectl logs -n phoenix job/manual-fe-<timestamp> -f
   ```

   Expected output:
   ```
   [INFO] Feature extraction starting
   [INFO] Found 523 parsed_trades without enriched_trades entry
   [INFO] Enriching trade 1/523 (AAPL, 2026-01-15)
   [INFO] Enriching trade 2/523 (TSLA, 2026-01-16)
   ...
   [INFO] Feature extraction complete: 523 rows inserted
   ```

3. Verify row count:
   ```bash
   kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
   SELECT COUNT(*) FROM enriched_trades;
   "
   # Should match parsed_trades count
   ```

#### If CronJob is failing silently

1. Check for TIINGO_API_KEY in CronJob env:
   ```bash
   kubectl get cronjob feature-extraction -n phoenix -o yaml | grep -A5 "env:"
   ```

2. If missing, add via Helm values:
   ```yaml
   # helm/phoenix/values.yaml
   featureExtraction:
     env:
       TIINGO_API_KEY:
         secretKeyRef:
           name: phoenix-secrets
           key: TIINGO_API_KEY
   ```

3. Apply:
   ```bash
   helm upgrade phoenix helm/phoenix -n phoenix --wait
   ```

### Verification

```bash
# Feature store is populated
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT COUNT(*) FROM enriched_trades;
"
# Expected: >90% of parsed_trades count

# Next backtest completes in <2 min
# Check dashboard or query:
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT id, status, updated_at - created_at AS duration
FROM agent_backtests
WHERE created_at >= NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 5;
"
# Expected: duration < 00:02:00
```

---

## 4. Redis Stream Backlog Growing

### Symptom

```bash
kubectl exec -n phoenix redis-0 -- redis-cli XLEN backtest:requests
# 47  (expected: 0-2)
```

New backtests queue up but never transition to `RUNNING`. Worker pod is running but not consuming.

### Diagnostic Steps

#### 4.1 Check worker pod is alive

```bash
kubectl get pods -n phoenix | grep backtest-worker
# Expected: 1/1 Running
```

```bash
kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=50
```

**Look for:**
- `XREADGROUP: no new entries, waiting...` (normal idle state)
- `XREADGROUP: error NOGROUP` → Consumer group doesn't exist
- No logs for >5 min → Worker is hung or infinite loop

#### 4.2 Check consumer group exists

```bash
kubectl exec -n phoenix redis-0 -- redis-cli XINFO GROUPS backtest:requests

# Expected output:
# 1) 1) "name"
#    2) "backtest-workers"
#    3) "consumers"
#    4) (integer) 1
#    5) "pending"
#    6) (integer) 0

# If "ERR no such key", the stream doesn't exist (first backtest will auto-create)
# If "NOGROUP", consumer group not initialized
```

#### 4.3 Check pending entries

```bash
kubectl exec -n phoenix redis-0 -- redis-cli XPENDING backtest:requests backtest-workers - + 10

# Shows entries delivered to consumer but not ACK'd
# If count > 5, worker may be processing but failing to ACK
```

### Fix

#### If consumer group missing

1. Recreate consumer group:
   ```bash
   kubectl exec -n phoenix redis-0 -- redis-cli XGROUP CREATE backtest:requests backtest-workers 0 MKSTREAM
   ```

2. Restart worker:
   ```bash
   kubectl rollout restart deployment/phoenix-backtest-worker -n phoenix
   ```

#### If worker is hung (processing but not ACKing)

1. Check for deadlock in worker logs:
   ```bash
   kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=500 | grep -E "ERROR|Exception|Traceback"
   ```

2. If no errors, restart worker:
   ```bash
   kubectl delete pod -n phoenix -l app.kubernetes.io/component=phoenix-backtest-worker
   # Pod auto-recreates
   ```

#### If backlog is legitimate (many backtests queued)

1. Scale worker to 2 replicas (requires RWX PVC or job isolation):
   ```bash
   # NOT SUPPORTED YET (PVC is ReadWriteOnce)
   # Future: switch to RWX or K8s Jobs per backtest
   ```

2. Wait for worker to process queue (1 backtest ~2 min → 47 backtests = ~90 min)

### Verification

```bash
# Stream length decreases over time
watch -n 5 'kubectl exec -n phoenix redis-0 -- redis-cli XLEN backtest:requests'

# All backtests transition to RUNNING within 10s of QUEUED
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT status, COUNT(*) FROM agent_backtests
WHERE created_at >= NOW() - INTERVAL '1 hour'
GROUP BY status;
"
# Expected: QUEUED=0, RUNNING=1, COMPLETED=<rest>
```

---

## 5. Tiingo API Key Expired

### Symptom

Worker logs show:
```
TiingoProvider: 401 Unauthorized
TiingoProvider: API key invalid or expired
enrich.py: falling back to yfinance
```

Backtests complete but take 10-15 min instead of <2 min (yfinance is slow).

### Diagnostic Steps

#### 5.1 Test Tiingo API key

```bash
kubectl exec -n phoenix deploy/phoenix-backtest-worker -- env | grep TIINGO_API_KEY
# TIINGO_API_KEY=<redacted>

# Test key
TIINGO_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.TIINGO_API_KEY}' | base64 -d)
curl -H "Authorization: Token $TIINGO_KEY" https://api.tiingo.com/api/test

# Expected: {"message":"You successfully sent a request"}
# If 401: key is invalid or expired
```

#### 5.2 Check Tiingo account status

1. Log in to https://www.tiingo.com/account/api
2. Check "API Key Status" → should be "Active"
3. Check "Usage" → free tier is 1000 requests/hour

### Fix

#### If API key expired

1. Generate new key from Tiingo dashboard (https://www.tiingo.com/account/api)

2. Seal new secret:
   ```bash
   kubectl create secret generic phoenix-secrets-new \
     --from-literal=TIINGO_API_KEY=<new-key> \
     --from-literal=POSTGRES_PASSWORD=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d) \
     --from-literal=JWT_SECRET_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.JWT_SECRET_KEY}' | base64 -d) \
     --from-literal=CREDENTIAL_ENCRYPTION_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.CREDENTIAL_ENCRYPTION_KEY}' | base64 -d) \
     --from-literal=ANTHROPIC_API_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.ANTHROPIC_API_KEY}' | base64 -d) \
     --from-literal=MINIO_ROOT_USER=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d) \
     --from-literal=MINIO_ROOT_PASSWORD=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 -d) \
     --dry-run=client -o yaml | \
     kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system -o yaml > sealed-secret-new.yaml

   kubectl apply -f sealed-secret-new.yaml -n phoenix
   ```

3. Restart worker and CronJob:
   ```bash
   kubectl rollout restart deployment/phoenix-backtest-worker -n phoenix
   kubectl delete job -n phoenix -l app.kubernetes.io/component=feature-extraction
   ```

#### If rate limit hit (1000 req/hour)

1. Wait 1 hour for reset, OR

2. Upgrade to paid tier ($10/mo for 10k req/hour):
   - Go to https://www.tiingo.com/account/billing
   - Subscribe to "Starter" plan
   - No code changes needed (same API key)

### Verification

```bash
# Test new key
TIINGO_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.TIINGO_API_KEY}' | base64 -d)
curl -H "Authorization: Token $TIINGO_KEY" https://api.tiingo.com/api/test
# Expected: 200 OK with success message

# Next backtest uses Tiingo (not yfinance fallback)
kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=100 | grep -i tiingo
# Expected: "TiingoProvider: fetched AAPL daily bars (200 OK)"
```

---

## 6. Need to Backfill Daily Bars

### Symptom

Feature-extraction CronJob logs show:
```
[WARNING] daily_bars table is empty, falling back to yfinance
```

Enrich step is slow despite feature store existing.

### Fix

Run the backfill script:

```bash
# Option A: From your Mac (requires TIINGO_API_KEY in local .env)
python scripts/backfill_daily_bars.py --years 5

# Option B: Via kubectl exec
kubectl exec -it -n phoenix deploy/phoenix-api -- bash
cd /app
export TIINGO_API_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.TIINGO_API_KEY}' | base64 -d)
python scripts/backfill_daily_bars.py --years 5
```

**Arguments:**
- `--years 5` → backfill last 5 years (default: 2)
- `--tickers AAPL TSLA SPY` → only backfill specific tickers (default: all from parsed_trades)

**Expected duration:** ~30 minutes for 60 tickers × 5 years

### Verification

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT
    COUNT(*) AS total_bars,
    COUNT(DISTINCT ticker) AS tickers,
    MIN(date) AS earliest,
    MAX(date) AS latest
FROM daily_bars;
"

# Expected:
# total_bars | tickers | earliest   | latest
# -----------+---------+------------+------------
#  75600     | 60      | 2021-05-12 | 2026-05-12
```

---

## 7. Manual Backtest Re-Enqueue

If a backtest is stuck in `RUNNING` state and worker logs show no activity, manually re-enqueue:

```bash
# Get backtest config from DB
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT id, agent_id, config FROM agent_backtests WHERE id = '<backtest-id>';
"

# Mark as FAILED (so UI shows it's not stuck)
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
UPDATE agent_backtests SET status = 'FAILED', error_message = 'Manual re-enqueue by operator'
WHERE id = '<backtest-id>';
"

# Re-enqueue via API endpoint (requires JWT token)
curl -X POST https://cashflowus.com/api/v2/agents/<agent-id>/backtest/retry \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json"
```

Alternatively, manually publish to Redis stream:

```bash
kubectl exec -n phoenix redis-0 -- redis-cli XADD backtest:requests "*" \
  backtest_id "<backtest-id>" \
  agent_id "<agent-id>" \
  config '{"channel_id":"...","risk_config":{...}}'
```

---

## Contact

**Escalation:** Platform team via #phoenix-ops Slack channel  
**On-call:** PagerDuty rotation (for Sev-1 issues only — backtest failures are Sev-2)
