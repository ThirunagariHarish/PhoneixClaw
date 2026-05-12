# ADR 0007: Feature Store and Out-of-Process Backtest

**Status:** Accepted

**Date:** 2026-05-12

**Deciders:** Platform team, SRE lead

**Related:**
- [Feature Store & Worker-Pod Architecture](../feature-store-and-worker-pod-2026-05-12.md)
- [Backtest Pipeline Troubleshooting Runbook](../../operations/runbooks/backtest-pipeline-troubleshooting.md)

---

## Context

Phoenix's backtesting pipeline is the critical path for onboarding new trading agents. Users backtest a Discord channel's historical signals to train ML models and discover trading patterns, then deploy the resulting agent to live trading. The original design ran backtests as `asyncio.create_task()` calls inside the FastAPI server (`phoenix-api` pod), with yfinance API calls for enrichment and ephemeral storage in `/app/data/`.

This architecture failed in production due to four critical issues:

1. **Orphaned subprocesses on helm upgrade:** When the `phoenix-api` pod restarted (helm upgrade, OOM kill, node drain), the backtest agent process tree was SIGKILL'd mid-run, leaving the backtest record stuck in `RUNNING` state with no way to resume. Operators manually marked backtests as `FAILED` and users re-ran from scratch, losing 15-30 minutes of compute.

2. **30-minute enrich timeouts:** The enrichment step fetched ~200 features per trade via yfinance's free tier (rate-limited to 2000 requests/hour). For 500-trade backtests spanning 60 tickers, this meant 30,000+ API calls. yfinance's undocumented rate limits triggered random 429 errors and exponential backoff, pushing enrich time from 5 minutes to 30+ minutes. Ad-hoc retry logic was added over multiple weeks but did not solve the underlying problem.

3. **Lack of observability:** Backtests ran in asyncio tasks with stdout redirected to container logs. Users saw only "RUNNING → COMPLETED" in the dashboard. When a backtest stalled (common with yfinance), operators kubectl-exec'd into the pod and tailed logs manually to diagnose. No granular progress tracking existed.

4. **Ephemeral storage:** The working directory (`/app/data/backtest_{agent_id}/`) was on the pod's ephemeral filesystem. On helm upgrade, all intermediate outputs (transformed.parquet, enriched.parquet, trained models) were lost. Re-runs re-fetched all data, re-trained all models, even if only the final LLM analysis step failed.

The design worked for demo-sized backtests (10-20 trades, single channel) but collapsed under production workloads (500+ trades, multi-channel, nightly re-training).

---

## Decision

We will adopt a **feature-store + worker-pod architecture** with the following components:

1. **Feature Store:** Two new PostgreSQL tables (`enriched_trades`, `daily_bars`) to cache expensive feature computation and historical OHLCV data. Populated nightly by a `feature-extraction` Kubernetes CronJob. Eliminates repeated yfinance API calls across backtests.

2. **Out-of-Process Worker:** A separate `phoenix-backtest-worker` Deployment that consumes backtest jobs from a Redis stream (`backtest:requests`) and runs the orchestrator with its own PVC-backed persistent storage. Survives helm upgrades and provides resumability.

3. **Tiingo as Primary Data Source:** Switch from yfinance (unreliable free tier) to Tiingo REST API (1000 req/hour, 20 years of daily data, stable). yfinance becomes fallback only.

4. **MarketDataProvider Abstraction:** A factory pattern in `shared/market_data/` to swap between Tiingo, yfinance, and future providers (Polygon, Alpha Vantage) without changing enrichment logic.

5. **Granular Progress Tracking:** A new table `agent_backtest_step_logs` captures per-step progress (e.g., "Feature: enrich [78/500 trades, 15.6% complete]"). Exposed via API and WebSocket for real-time dashboard updates.

6. **Fallback Paths:** If Redis is down, backtests fall back to the old in-process path via `PHOENIX_BACKTEST_INLINE=1` env var. If feature store is empty, enrich.py falls back to inline computation. If Tiingo rate-limits, fall back to yfinance.

---

## Consequences

### Positive

1. **90% faster backtests:** With feature-store cache hits, 500-trade backtests complete in <2 minutes (down from 15-30 min). Enrich step skips 95%+ API calls on repeat backtests.

2. **Zero data loss on deploy:** PVCs persist intermediate outputs (`phoenix-price-cache` 5Gi, `phoenix-backtest-data` 20Gi). Helm upgrades no longer orphan backtests.

3. **Resumability:** Future enhancement can resume from last completed step using `agent_backtest_step_logs` table as checkpoint.

4. **Observable:** Dashboard shows real-time step progress. Operators query `agent_backtest_step_logs` to see exactly where a backtest stalled. No more kubectl exec log tailing.

5. **Reliable data source:** Tiingo's REST API is stable and well-documented (1000 req/hour, no hidden rate limits). yfinance is demoted to fallback only.

6. **Horizontally scalable (future):** Redis stream consumer pattern enables multiple worker replicas when PVC is switched to ReadWriteMany (Longhorn/NFS) or per-backtest Jobs are introduced.

### Negative

1. **More services to operate:** Added `phoenix-backtest-worker` Deployment and `feature-extraction` CronJob. Two more pods to monitor, troubleshoot, and upgrade.

2. **Schema versioning burden:** The `enriched_trades.computed_version` column enables coexistence of v1/v2 features, but breaking changes require manual backfill or acceptance of degraded performance for old backtests.

3. **Redis is now critical:** If Redis is down, new backtests can't be enqueued (unless `PHOENIX_BACKTEST_INLINE=1` is set). Redis was previously optional (used only for pub/sub).

4. **PVC growth:** `phoenix-backtest-data` (20Gi) fills at ~15 GB/year. Cleanup policy (delete backtests >90 days old) must be implemented to avoid manual intervention.

5. **Single-replica bottleneck:** Worker is single-replica (serialized backtests) to avoid OOM issues. If the worker pod crashes, new backtests queue up until restart. Future scaling requires multi-replica support or per-backtest Jobs.

6. **Tiingo API key dependency:** Free tier is 1000 req/hour. If exceeded, backtests fall back to yfinance (slower, less reliable). Paid tier ($10/mo for 10k req/hour) needed if >50 backtests/day.

---

## Alternatives Considered

### 1. Celery Task Queue

**Rejected:** Celery requires a separate broker (RabbitMQ or Redis) and result backend. Overkill for single-replica worker. Redis Streams with a simple consumer loop is sufficient and has fewer moving parts.

### 2. Kubernetes Jobs per Backtest

**Rejected for v1, Reconsidered for v2:** Each backtest spawns a K8s Job. Pros: isolation, auto-cleanup, native retry. Cons: image-pull latency (~20s per job), no cross-job feature caching without external storage. Complexity is too high for initial rollout, but may revisit if concurrent backtests >5.

### 3. Argo Workflows

**Rejected:** Full DAG orchestration framework. Requires additional CRDs (Workflow, WorkflowTemplate), ArgoCD or kubectl apply to submit jobs. Adds complexity with little benefit over a simple Redis stream consumer. Phoenix already has agent orchestration; doesn't need a second orchestration layer.

### 4. Keep In-Process, Add PVC to phoenix-api

**Rejected:** Mounting PVC to phoenix-api solves ephemeral storage but not orphaned subprocesses. If the pod restarts mid-backtest, the asyncio task is still lost. Also doesn't solve observability or yfinance reliability issues.

### 5. Build a Custom Feature Store Service (HTTP API)

**Rejected:** Postgres with JSONB is sufficient for v1. A dedicated feature-serving HTTP API (ala Feast/Tecton) is overkill for 200-feature vectors with ~10 QPS read load. Revisit if read latency becomes a bottleneck (unlikely given <2ms Postgres query times).

---

## Implementation Notes

**Migration:** `051_feature_store` (applied 2026-05-12) creates the three new tables (`enriched_trades`, `daily_bars`, `agent_backtest_step_logs`).

**Deployment:** Helm chart updated with:
- `phoenix-backtest-worker-deployment.yaml` (1 replica, 4Gi memory, two PVCs)
- `feature-extraction-cronjob.yaml` (schedule: "0 3 * * *", 2Gi memory)
- `phoenix-price-cache-pvc.yaml` (5Gi ReadWriteOnce)
- `phoenix-backtest-data-pvc.yaml` (20Gi ReadWriteOnce)

**Backward Compatibility:**
- `PHOENIX_BACKTEST_INLINE=1` env var forces the old in-process path (for local dev or Redis outage)
- Existing backtests (pre-migration) continue to work via inline enrich (no feature-store data yet)
- API endpoints unchanged (POST /api/v2/agents still creates backtests the same way)

**Rollout Plan:**
1. Apply migration, deploy new Helm chart
2. Backfill daily bars: `python scripts/backfill_daily_bars.py --years 5` (one-time, ~30 min)
3. Trigger initial feature-extraction run: `kubectl create job --from=cronjob/feature-extraction manual-fe-$(date +%s)` (populates feature store for existing parsed_trades)
4. Monitor first 10 backtests for errors (Tiingo API key, PVC permissions, Redis stream lag)
5. If stable after 48 hours, remove `PHOENIX_BACKTEST_INLINE` fallback from documentation (keep env var for emergencies)

**Success Criteria:**
- 95%+ of backtests complete in <2 minutes (with feature-store cache hits)
- 0 orphaned backtests in 7 days post-rollout
- <5% backtest failure rate (down from 15-20%)

---

## References

- [Tecton — Robinhood Feature Store using Feast](https://www.tecton.ai/apply/session-video-archive/how-robinhood-built-a-feature-store-using-feast/) (inspiration for schema design)
- [Redis Streams Documentation](https://redis.io/docs/data-types/streams/) (consumer group semantics)
- [Tiingo API Documentation](https://api.tiingo.com/documentation/general/overview) (rate limits, data coverage)
- [Alembic Migration 051_feature_store](../../shared/db/migrations/versions/051_feature_store.py) (DDL)
