# Feature Store Setup Runbook

**Purpose:** Day-0 migration guide for the feature-store + worker-pod backtest architecture  
**Date:** 2026-05-12  
**Prerequisites:**
- Helm chart deployed (includes new Deployments and CronJob)
- `kubectl` access to the `phoenix` namespace
- Postgres user `phoenixtrader` with write access

**Related Docs:**
- [Feature Store & Worker-Pod Architecture](../architecture/feature-store-and-worker-pod-2026-05-12.md)
- [ADR 0007: Feature Store and Out-of-Process Backtest](../architecture/adrs/0007-feature-store-and-out-of-process-backtest.md)
- [Backtest Pipeline Troubleshooting Runbook](runbooks/backtest-pipeline-troubleshooting.md)

---

## Overview

This runbook walks through the one-time setup required to migrate from the old in-process backtest pipeline to the new feature-store + worker-pod architecture. Follow these steps in order on a fresh deployment or when upgrading from pre-2026-05-12 releases.

**Estimated time:** 60-90 minutes (mostly waiting for backfill scripts)

---

## Step 1: Apply Database Migration

The migration `051_feature_store` creates three new tables:
- `enriched_trades` — cached feature vectors (200+ columns per trade)
- `daily_bars` — historical OHLCV data from Tiingo
- `agent_backtest_step_logs` — granular progress tracking

### 1.1 Check current migration head

```bash
# From your Mac (with repo cloned)
cd /Users/harishkumar/Projects/TradingBot/ProjectPhoneix

# Show current migration
make db-alembic-heads
# Expected output: 050_merge_heads_engine_type (or older)
```

### 1.2 Apply migration

**Option A: Via Makefile (local dev)**
```bash
make db-upgrade
# Runs: alembic upgrade head
```

**Option B: Via kubectl exec (production)**
```bash
kubectl exec -it -n phoenix deploy/phoenix-api -- bash
cd /app
export DATABASE_URL="postgresql+asyncpg://phoenixtrader:${POSTGRES_PASSWORD}@postgres:5432/phoenixtrader"
alembic upgrade head
exit
```

### 1.3 Verify migration applied

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "\dt" | grep -E "enriched_trades|daily_bars|agent_backtest_step_logs"

# Expected output:
# public | enriched_trades            | table | phoenixtrader
# public | daily_bars                 | table | phoenixtrader
# public | agent_backtest_step_logs   | table | phoenixtrader
```

If tables exist, proceed to Step 2.

---

## Step 2: Set TIINGO_API_KEY in phoenix-secrets

Tiingo is the primary data source for daily OHLCV bars (yfinance is fallback only).

### 2.1 Obtain Tiingo API key

1. Sign up at https://www.tiingo.com/account/api (free tier: 1000 req/hour)
2. Copy the API key from the dashboard

### 2.2 Add to phoenix-secrets via kubeseal

**If `phoenix-secrets` already exists** (most common):

```bash
# Export existing secrets
POSTGRES_PASSWORD=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
JWT_SECRET_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.JWT_SECRET_KEY}' | base64 -d)
CREDENTIAL_ENCRYPTION_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.CREDENTIAL_ENCRYPTION_KEY}' | base64 -d)
ANTHROPIC_API_KEY=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.ANTHROPIC_API_KEY}' | base64 -d)
MINIO_ROOT_USER=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d)
MINIO_ROOT_PASSWORD=$(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 -d)

# Create new secret with TIINGO_API_KEY added
kubectl create secret generic phoenix-secrets \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET_KEY" \
  --from-literal=CREDENTIAL_ENCRYPTION_KEY="$CREDENTIAL_ENCRYPTION_KEY" \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --from-literal=MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  --from-literal=MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  --from-literal=TIINGO_API_KEY="<your-tiingo-key>" \
  --dry-run=client -o yaml | \
  kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system -o yaml > phoenix-secrets-sealed.yaml

# Apply sealed secret
kubectl apply -f phoenix-secrets-sealed.yaml -n phoenix
```

**If starting from scratch** (new cluster):

```bash
# Generate secrets
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET_KEY=$(openssl rand -hex 32)
CREDENTIAL_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ANTHROPIC_API_KEY="<your-anthropic-key>"
MINIO_ROOT_USER="minioadmin"
MINIO_ROOT_PASSWORD=$(openssl rand -hex 16)
TIINGO_API_KEY="<your-tiingo-key>"

# Seal and apply
kubectl create secret generic phoenix-secrets \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET_KEY" \
  --from-literal=CREDENTIAL_ENCRYPTION_KEY="$CREDENTIAL_ENCRYPTION_KEY" \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --from-literal=MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  --from-literal=MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  --from-literal=TIINGO_API_KEY="$TIINGO_API_KEY" \
  --dry-run=client -o yaml | \
  kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system -o yaml > phoenix-secrets-sealed.yaml

kubectl apply -f phoenix-secrets-sealed.yaml -n phoenix
```

### 2.3 Verify secret updated

```bash
kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.TIINGO_API_KEY}' | base64 -d
# Should output your Tiingo API key
```

---

## Step 3: Deploy Updated Helm Chart

The new Helm chart includes:
- `phoenix-backtest-worker` Deployment (1 replica, 4Gi memory)
- `feature-extraction` CronJob (schedule: 0 3 * * *)
- `phoenix-price-cache` PVC (5Gi ReadWriteOnce)
- `phoenix-backtest-data` PVC (20Gi ReadWriteOnce)

### 3.1 Deploy via CD (recommended)

**If using GitHub Actions CD:**

```bash
# From your Mac
cd /Users/harishkumar/Projects/TradingBot/ProjectPhoneix
git add helm/phoenix/templates/phoenix-backtest-worker-deployment.yaml \
        helm/phoenix/templates/feature-extraction-cronjob.yaml \
        helm/phoenix/templates/phoenix-price-cache-pvc.yaml \
        helm/phoenix/templates/phoenix-backtest-data-pvc.yaml
git commit -m "feat: add feature-store and worker-pod architecture"
git push origin main

# CD pipeline auto-deploys to production
# Monitor via https://github.com/<user>/PhoneixClaw/actions
```

Wait for CD to complete (~5-10 min).

### 3.2 Deploy manually (local dev or hotfix)

```bash
# From your Mac
helm upgrade --install phoenix helm/phoenix -n phoenix \
  --set image.tag=main-$(git rev-parse --short HEAD) \
  --wait --timeout 5m

# Or on the VPS directly
ssh -i ~/.ssh/coolify_deploy root@69.62.86.166 "
cd /root/phoenix
git pull origin main
helm upgrade --install phoenix helm/phoenix -n phoenix \
  --set image.tag=main-$(git rev-parse --short HEAD) \
  --wait --timeout 5m
"
```

### 3.3 Verify new pods are running

```bash
kubectl get pods -n phoenix | grep -E "backtest-worker|feature-extraction"

# Expected output:
# phoenix-backtest-worker-abc123-xyz  1/1  Running  0  2m
# (feature-extraction CronJob creates a Job only at 03:00 UTC — no pod yet)

kubectl get cronjobs -n phoenix
# NAME                  SCHEDULE     SUSPEND  ACTIVE  LAST SCHEDULE  AGE
# feature-extraction    0 3 * * *    False    0       <none>         2m
```

### 3.4 Verify PVCs are bound

```bash
kubectl get pvc -n phoenix | grep -E "phoenix-price-cache|phoenix-backtest-data"

# Expected output:
# phoenix-price-cache     Bound  pvc-abc123  5Gi   RWO  local-path  2m
# phoenix-backtest-data   Bound  pvc-xyz789  20Gi  RWO  local-path  2m
```

If PVCs are `Pending`, check node disk space:
```bash
df -h / | grep -v Filesystem
# Should have >30 GB free (25Gi for PVCs + 5Gi headroom)
```

---

## Step 4: Backfill Daily Bars

The `daily_bars` table stores historical OHLCV data from Tiingo. This is a one-time backfill (incremental updates happen via feature-extraction CronJob).

### 4.1 Run backfill script

**Option A: From your Mac** (requires TIINGO_API_KEY in local .env)

```bash
cd /Users/harishkumar/Projects/TradingBot/ProjectPhoneix

# Add TIINGO_API_KEY to .env if not already present
echo "TIINGO_API_KEY=<your-key>" >> .env

# Run backfill (this takes ~30 minutes)
python scripts/backfill_daily_bars.py --years 5
```

**Option B: Via kubectl exec** (production)

```bash
kubectl exec -it -n phoenix deploy/phoenix-api -- bash

# Inside the pod
export DATABASE_URL="postgresql+asyncpg://phoenixtrader:${POSTGRES_PASSWORD}@postgres:5432/phoenixtrader"
export TIINGO_API_KEY=$(cat /dev/stdin <<< $(kubectl get secret phoenix-secrets -n phoenix -o jsonpath='{.data.TIINGO_API_KEY}' | base64 -d))

cd /app
python scripts/backfill_daily_bars.py --years 5

# This prints progress every 10 tickers:
# [INFO] Backfilling AAPL: 1260 bars inserted
# [INFO] Backfilling TSLA: 1008 bars inserted
# ...
# [INFO] Backfill complete: 75600 bars across 60 tickers

exit
```

**Arguments:**
- `--years 5` → backfill last 5 years (default: 2)
- `--tickers AAPL TSLA SPY` → only backfill specific tickers (default: all unique tickers from `parsed_trades`)

### 4.2 Verify daily_bars populated

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT
    COUNT(*) AS total_bars,
    COUNT(DISTINCT ticker) AS unique_tickers,
    MIN(date) AS earliest_date,
    MAX(date) AS latest_date
FROM daily_bars;
"

# Expected output (for 60 tickers × 5 years):
#  total_bars | unique_tickers | earliest_date | latest_date
# ------------+----------------+---------------+-------------
#   75600     |      60        | 2021-05-12    | 2026-05-12
```

If `total_bars` is 0, the backfill failed. Check:
- `TIINGO_API_KEY` is valid (test with `curl -H "Authorization: Token $KEY" https://api.tiingo.com/api/test`)
- Network connectivity from phoenix-api pod to api.tiingo.com

---

## Step 5: Trigger Initial Feature-Extraction Run

The feature-extraction CronJob runs nightly at 03:00 UTC, but we need to populate the feature store immediately for existing `parsed_trades`.

### 5.1 Manually trigger the CronJob

```bash
kubectl create job --from=cronjob/feature-extraction manual-fe-$(date +%s) -n phoenix

# Get job name
kubectl get jobs -n phoenix | grep manual-fe
# manual-fe-1715529600  1/1  10m  10m
```

### 5.2 Monitor job logs

```bash
kubectl logs -n phoenix job/manual-fe-<timestamp> -f

# Expected output:
# [INFO] Feature extraction starting
# [INFO] Found 523 parsed_trades without enriched_trades entry
# [INFO] Enriching trade 1/523: AAPL @ 2026-01-15T14:30:00
# [INFO] Fetching daily bars from Tiingo: AAPL (2026-01-08 to 2026-01-15)
# [INFO] Computing 200+ features: price_action, technicals, volume_profile, sentiment
# [INFO] Inserted enriched_trades row (parsed_trade_id=abc-123, computed_version=v1)
# [INFO] Enriching trade 2/523: TSLA @ 2026-01-16T09:45:00
# ...
# [INFO] Feature extraction complete: 523/523 trades enriched, 0 errors
```

**Expected duration:** ~10-15 minutes for 500 trades (depends on Tiingo API latency)

### 5.3 Verify enriched_trades populated

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT
    COUNT(*) AS enriched_count,
    COUNT(DISTINCT ticker) AS unique_tickers,
    MIN(computed_at) AS first_computed,
    MAX(computed_at) AS last_computed
FROM enriched_trades;
"

# Expected:
#  enriched_count | unique_tickers | first_computed        | last_computed
# ----------------+----------------+-----------------------+-----------------------
#       523       |       45       | 2026-05-12 10:15:23   | 2026-05-12 10:28:14
```

### 5.4 Check feature store coverage

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

# Expected: coverage_pct = 100.00 (all recent trades have enriched entries)
```

If coverage < 95%, check job logs for errors (missing Tiingo API key, network issues, invalid tickers).

---

## Step 6: Verify a Backtest Completes in <2 Minutes

This is the end-to-end smoke test for the new architecture.

### 6.1 Trigger a backtest via dashboard

1. Go to https://cashflowus.com/ (or your Phoenix URL)
2. Log in → Agents tab
3. Click "+ New Agent"
4. Select a Discord connector with at least 50 trades
5. Set risk config (stop_loss_pct=0.02, max_position_pct=0.1)
6. Click "Create"

### 6.2 Monitor backtest progress

**Option A: Via dashboard** (real-time WebSocket updates)
- Progress bar shows "Feature: transform → Feature: enrich → Model: train → ..."
- Enrich step should complete in <30 seconds (with feature-store cache hits)

**Option B: Via database**
```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT id, status, current_step, progress_pct, created_at, updated_at
FROM agent_backtests
WHERE created_at >= NOW() - INTERVAL '10 minutes'
ORDER BY created_at DESC
LIMIT 1;
"

# Expected sequence (refresh every 10s):
# status='QUEUED', current_step=NULL, progress_pct=0
# status='RUNNING', current_step='Feature: transform', progress_pct=8
# status='RUNNING', current_step='Feature: enrich', progress_pct=16
# status='RUNNING', current_step='Model: train', progress_pct=50
# ...
# status='COMPLETED', current_step='Validate: live_agent', progress_pct=100
```

**Option C: Via worker logs**
```bash
kubectl logs -n phoenix deploy/phoenix-backtest-worker -f | grep -E "enrich|train|COMPLETED"
```

### 6.3 Verify completion time

```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
SELECT
    id,
    status,
    EXTRACT(EPOCH FROM (updated_at - created_at)) AS duration_seconds
FROM agent_backtests
WHERE created_at >= NOW() - INTERVAL '10 minutes'
ORDER BY created_at DESC
LIMIT 1;
"

# Expected:
#  id       | status    | duration_seconds
# ----------+-----------+------------------
#  abc-123  | COMPLETED |       87.3
```

**Success criteria:** `duration_seconds < 120` (2 minutes)

If duration > 300 (5 minutes), the feature store is not being used. Check:
- Worker logs show "feature store miss" → feature-extraction job failed or incomplete
- Worker logs show "falling back to yfinance" → Tiingo API key missing or rate-limited

---

## Step 7: Schedule Regular Feature-Extraction Runs

The CronJob is already scheduled (0 3 * * * = 3 AM UTC daily), but verify it will run.

### 7.1 Check CronJob schedule

```bash
kubectl get cronjobs -n phoenix feature-extraction -o yaml | grep schedule
# schedule: 0 3 * * *
```

### 7.2 Check suspend status

```bash
kubectl get cronjobs -n phoenix feature-extraction -o yaml | grep suspend
# suspend: false
```

If `suspend: true`, the CronJob won't run. Fix:
```bash
kubectl patch cronjob feature-extraction -n phoenix -p '{"spec":{"suspend":false}}'
```

### 7.3 Verify next scheduled run

```bash
kubectl get cronjobs -n phoenix feature-extraction
# NAME                  SCHEDULE     SUSPEND  ACTIVE  LAST SCHEDULE  AGE
# feature-extraction    0 3 * * *    False    0       10m ago        2h
```

`LAST SCHEDULE` shows when the job last ran (should update daily at 03:00 UTC).

### 7.4 (Optional) Adjust schedule for testing

To test immediately:
```bash
# Run every 5 minutes (for testing only)
kubectl patch cronjob feature-extraction -n phoenix -p '{"spec":{"schedule":"*/5 * * * *"}}'

# Wait 5 minutes, check logs
kubectl get jobs -n phoenix | grep feature-extraction
kubectl logs -n phoenix job/<job-name>

# Reset to nightly
kubectl patch cronjob feature-extraction -n phoenix -p '{"spec":{"schedule":"0 3 * * *"}}'
```

---

## Step 8: (Optional) Enable Inline Fallback for Local Dev

For local development (Docker Compose), the worker pod doesn't exist. Use the inline fallback:

### 8.1 Set environment variable

```bash
# In .env file
echo "PHOENIX_BACKTEST_INLINE=1" >> .env
```

Or in `docker-compose.yml`:
```yaml
services:
  phoenix-api:
    environment:
      PHOENIX_BACKTEST_INLINE: "1"
```

### 8.2 Verify inline backtests work

```bash
# Start local stack
make dev-run

# Trigger a backtest via dashboard (http://localhost:3000)
# Check phoenix-api logs:
docker compose logs phoenix-api -f | grep "Backtest.*inline"
# Expected: "Backtest abc-123 enqueued inline (PHOENIX_BACKTEST_INLINE=1)"
```

**Note:** Inline backtests still orphan on container restart. Only use for local dev.

---

## Troubleshooting

### Issue: Migration fails with "relation enriched_trades already exists"

**Cause:** Migration was partially applied or manually created.

**Fix:**
```bash
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c "
DROP TABLE IF EXISTS agent_backtest_step_logs CASCADE;
DROP TABLE IF EXISTS enriched_trades CASCADE;
DROP TABLE IF EXISTS daily_bars CASCADE;
"

# Re-run migration
kubectl exec -it -n phoenix deploy/phoenix-api -- alembic upgrade head
```

### Issue: Tiingo API key not found

**Symptom:** feature-extraction job logs show `TiingoProvider: TIINGO_API_KEY not set`

**Fix:** Check Step 2.3 above. Ensure secret is sealed and applied.

### Issue: PVCs are stuck in Pending

**Symptom:**
```bash
kubectl get pvc -n phoenix | grep phoenix-price-cache
# phoenix-price-cache  Pending  ...
```

**Cause:** Node disk is full or StorageClass doesn't exist.

**Fix:**
```bash
# Check disk space
df -h / | grep -v Filesystem
# If <5 GB free, clean up old Docker images/volumes

# Check StorageClass
kubectl get storageclass
# Should show 'local-path' (k3s default)

# If missing, install local-path-provisioner
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml
```

### Issue: Backtest still takes 10+ minutes

**Symptom:** Backtest completes but duration is 600+ seconds (same as old pipeline).

**Cause:** Feature store is not being used (cache misses).

**Diagnosis:**
```bash
kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=100 | grep "feature store"
# If you see "feature store miss for trade 1/500", the feature-extraction job didn't populate enriched_trades
```

**Fix:** Re-run Step 5 (trigger manual feature-extraction job). Wait for completion, then retry backtest.

---

## Rollback Plan

If the new architecture is unstable, roll back to the old in-process pipeline:

### 8.1 Set inline fallback flag

```bash
kubectl set env deployment/phoenix-api -n phoenix PHOENIX_BACKTEST_INLINE=1
kubectl rollout status deployment/phoenix-api -n phoenix
```

### 8.2 (Optional) Scale down worker

```bash
kubectl scale deployment phoenix-backtest-worker -n phoenix --replicas=0
```

### 8.3 Verify old pipeline works

Trigger a backtest via dashboard. It should run as an asyncio task inside phoenix-api (check `kubectl logs deploy/phoenix-api`).

**Note:** Old pipeline issues (orphaned subprocesses, slow yfinance) still apply. This is a temporary rollback only.

---

## Success Criteria

After completing all steps, the following should be true:

1. ✅ Migration `051_feature_store` applied → three new tables exist
2. ✅ `TIINGO_API_KEY` set in phoenix-secrets
3. ✅ `phoenix-backtest-worker` pod is Running (1/1)
4. ✅ `feature-extraction` CronJob scheduled (0 3 * * *)
5. ✅ PVCs `phoenix-price-cache` and `phoenix-backtest-data` are Bound
6. ✅ `daily_bars` table has >10k rows spanning 5 years
7. ✅ `enriched_trades` table has >90% coverage of `parsed_trades`
8. ✅ New backtests complete in <2 minutes (with feature-store cache hits)
9. ✅ Dashboard shows real-time step progress (WebSocket updates)
10. ✅ Worker logs show "Tiingo: 200 OK" (not "falling back to yfinance")

---

## Next Steps

- **Monitoring:** Add Prometheus alerts for `BacktestQueueDepthHigh`, `FeatureStoreCoverageLow` (see [Enterprise Readiness doc](../architecture/enterprise-readiness-2026-05-05.md))
- **Capacity planning:** Monitor PVC usage weekly (`kubectl exec -n phoenix deploy/phoenix-backtest-worker -- df -h /var/lib/phoenix/backtests`)
- **Cleanup policy:** Implement 90-day retention for old backtest directories (currently manual)
- **Multi-replica:** Switch PVC to ReadWriteMany (Longhorn/NFS) to enable 2+ worker replicas

---

## Contact

**Questions:** #phoenix-ops Slack channel  
**Issues:** File a GitHub issue in the PhoneixClaw repo (private)  
**Escalation:** Platform team on-call (PagerDuty)
