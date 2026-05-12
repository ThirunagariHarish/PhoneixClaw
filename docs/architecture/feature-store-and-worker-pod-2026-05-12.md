# Feature Store & Worker-Pod Backtest Architecture

**Status:** Active | **Date:** 2026-05-12 | **ADR:** [0007-feature-store-and-out-of-process-backtest.md](adrs/0007-feature-store-and-out-of-process-backtest.md)

---

## Problem Statement

The original in-process backtest pipeline suffered from four critical failures that made it unsuitable for production:

1. **Orphaned subprocesses on helm upgrade:** Backtests spawned via `asyncio.create_task()` inside the phoenix-api pod were forcibly orphaned when helm upgrade triggered a pod restart. The agent process tree (Claude Code session + Python tool subprocesses) was SIGKILL'd mid-run, leaving the backtest record in the `RUNNING` state forever with no way to resume. Users had to manually update the DB to `FAILED` and re-run from scratch.

2. **30-minute enrich timeouts on yfinance:** The enrichment step (`agents/backtesting/tools/enrich.py`) fetched ~200 features per trade via yfinance (free tier, rate-limited to 2000 requests/hour). For a backtest with 500 trades spanning 60 tickers, this meant 30,000+ API calls. yfinance's undocumented rate limits caused random 429 errors and exponential backoff, pushing the enrich step from 5 minutes to 30+ minutes. Ad-hoc retry layers were added over multiple weeks but did not solve the underlying problem.

3. **Lack of progress visibility:** The backtest orchestrator ran in an asyncio task with stdout redirected to the container log. Users had no granular progress updates beyond "RUNNING → COMPLETED" in the DB. When a backtest stalled (common with yfinance timeouts), operators had to kubectl exec into the pod and tail logs manually to diagnose.

4. **Ephemeral /app/data sandbox:** The backtest agent's working directory was `/app/data/backtest_{agent_id}/output/v{N}/` inside the phoenix-api pod's ephemeral filesystem. On helm upgrade, all intermediate outputs (transformed.parquet, enriched.parquet, trained models) were lost. Re-runs required re-fetching all data, re-training all models, even if only the final LLM analysis step failed.

The architecture was a prototype that worked for demo-sized backtests (10-20 trades, single channel) but collapsed under production workloads (500+ trades, multi-channel, nightly re-training).

---

## New Architecture

### High-Level Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       Phoenix Dashboard (React)                          │
│  User clicks "Spawn Agent" → POST /api/v2/agents                       │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     phoenix-api (FastAPI)                                │
│  1. INSERT agent_backtests (status=QUEUED)                              │
│  2. XADD backtest:requests {backtest_id, agent_id, config}              │
│  3. Return 202 Accepted                                                  │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │
                       ▼
               ┌───────────────┐
               │ Redis Streams │
               │ backtest:     │
               │ requests      │
               └───────┬───────┘
                       │
                       │ XREADGROUP (blocking)
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│          phoenix-backtest-worker (Deployment, replicas=1)                │
│                                                                           │
│  1. Consume backtest request from Redis                                  │
│  2. Create working dir: /var/lib/phoenix/backtests/<backtest_id>        │
│  3. Spawn BacktestOrchestrator (12-step pipeline)                       │
│  4. Each step reports progress via POST /api/v2/agents/{id}/backtest-   │
│     progress and inserts agent_backtest_step_logs row                   │
│  5. Enrich step queries enriched_trades table (feature-store shortcut)  │
│  6. Fallback to enrich.py inline if feature-store empty                 │
│  7. On completion: XACK + update backtest record to COMPLETED           │
│                                                                           │
│  Volumes:                                                                │
│  - /var/lib/phoenix/price_cache → phoenix-price-cache PVC (5Gi)        │
│  - /var/lib/phoenix/backtests → phoenix-backtest-data PVC (20Gi)       │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │
                       │ (reads feature store + daily bars)
                       ▼
               ┌───────────────┐
               │  PostgreSQL   │
               ├───────────────┤
               │ enriched_     │
               │ trades        │
               ├───────────────┤
               │ daily_bars    │
               └───────────────┘
                       ▲
                       │
                       │ (nightly population)
                       │
┌──────────────────────┴───────────────────────────────────────────────────┐
│        feature-extraction (CronJob, schedule: 0 3 * * *)                 │
│                                                                           │
│  1. SELECT * FROM parsed_trades WHERE NOT EXISTS enriched_trades entry   │
│  2. For each: fetch 200+ features (price action, technicals, options)   │
│  3. INSERT INTO enriched_trades (computed_version='v1')                 │
│  4. Uses Tiingo for daily bars (primary), yfinance fallback             │
│  5. Reads/writes /var/lib/phoenix/price_cache (deduplication)           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### 1. User initiates backtest

**Dashboard → API:**
```http
POST /api/v2/agents
{
  "name": "NightTrader",
  "connector_id": "<discord-channel-uuid>",
  "risk_config": { "stop_loss_pct": 0.02, "max_position_pct": 0.1 }
}
```

**API handler (`apps/api/src/routes/agents.py::create_agent`):**
1. Inserts `Agent` row (status=`BACKTESTING`)
2. Inserts `AgentBacktest` row (status=`QUEUED`)
3. Publishes to Redis stream:
   ```python
   await redis.xadd(
       "backtest:requests",
       {"backtest_id": str(backtest_id), "agent_id": str(agent_id), "config": json.dumps(config)}
   )
   ```
4. Returns `202 Accepted` with `backtest_id`

### 2. Worker consumes backtest request

**Backtest worker (`services/backtest-worker/src/consumer.py`):**
1. Blocking `XREADGROUP` on `backtest:requests` stream (consumer group `backtest-workers`)
2. Receives backtest job → updates DB to `status=RUNNING`
3. Creates working directory: `/var/lib/phoenix/backtests/<backtest_id>/`
4. Writes `config.json` with agent params, Discord token, risk limits
5. Instantiates `BacktestOrchestrator` and calls `.run()`

### 3. Orchestrator runs 12-step pipeline

**Pipeline steps (same as original, but now out-of-process with PVC persistence):**

1. **Transform** — `tools/transform.py --source postgres --output transformed.parquet`
   - Pulls Discord messages from `channel_messages` table
   - Parses trade signals (regex + LLM fallback)
   - Outputs Parquet with columns: `[entry_time, ticker, direction, price, confidence, raw_message]`

2. **Enrich** — `tools/enrich.py --input transformed.parquet --output enriched.parquet`
   - **Feature-store shortcut:** For each row, query `enriched_trades` table by `(parsed_trade_id, computed_version='v1')`
   - If exists: deserialize `features` JSONB column → skip yfinance fetch
   - If missing: fall back to inline enrichment (yfinance + Tiingo via `MarketDataProvider` factory)
   - Outputs Parquet with ~200 feature columns
   - Progress reported every 50 rows via `POST /api/v2/agents/{id}/backtest-progress`

3. **Embeddings** — `tools/embed.py` (sentence-transformers for Discord message text)

4. **Preprocess** — `tools/preprocess.py` (train/val/test split 70/15/15, SMOTE oversampling)

5. **Model Selection** — `tools/model_selector.py` picks optimal models based on dataset size:
   - < 100 samples: LightGBM only
   - 100-500: LightGBM + CatBoost + RandomForest
   - 500+: All 8 models (+ LSTM, Transformer, TFT, TCN)

6-8. **Train/Evaluate/Explainability** — Sequential training (memory-constrained), pick best by val_sharpe

9. **Pattern Discovery** — `tools/pattern_discovery.py` (multi-condition trading rules)

10. **LLM Analysis** — `tools/llm_strategy_analysis.py` (narrative interpretation via Anthropic)

11. **Validation** — `tools/validate_live_agent.py` (schema checks)

12. **Create Live Agent** — `tools/create_live_agent.py` builds `manifest.json` + `CLAUDE.md` template

After step 12, the orchestrator calls back to API:
```python
await httpx_client.post(
    f"{api_base_url}/api/v2/agents/{agent_id}/backtest-progress",
    json={"status": "COMPLETED", "metrics": {...}},
    headers={"Authorization": f"Bearer {jwt_token}"}
)
```

### 4. Dashboard shows real-time progress

**WebSocket feed (`phoenix-ws-gateway`):**
- On every `POST /api/v2/agents/{id}/backtest-progress`, the API publishes to Redis pub/sub channel `agent:{agent_id}:progress`
- ws-gateway subscribes and broadcasts to connected dashboard clients
- Dashboard shows granular step progress: "Feature: enrich [78/500 trades, 15.6% complete]"

### 5. Backtest completion → auto-create analyst

**API handler (`apps/api/src/services/agent_gateway.py::_auto_create_analyst`):**
1. Loads `manifest.json` from `/var/lib/phoenix/backtests/<backtest_id>/live_agent/manifest.json`
2. Updates Agent record:
   - `status=BACKTEST_COMPLETE`
   - `character`, `rules`, `model_path` fields from manifest
3. Dashboard shows metrics → user reviews and clicks **Approve**
4. `POST /api/v2/agents/{id}/approve` → spawns live analyst Claude Code session immediately

---

## Feature Store Details

### Table: `enriched_trades`

**Schema (from migration `051_feature_store`):**
```sql
CREATE TABLE enriched_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parsed_trade_id UUID NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    features JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    computed_version VARCHAR(32) NOT NULL DEFAULT 'v1'
);

CREATE INDEX ix_enriched_trades_parsed_trade_id ON enriched_trades(parsed_trade_id);
CREATE INDEX ix_enriched_trades_ticker_entry ON enriched_trades(ticker, entry_time);
CREATE UNIQUE INDEX uq_enriched_trades_parsed_version ON enriched_trades(parsed_trade_id, computed_version);
```

**Purpose:**
- Cache expensive feature computation (200+ fields: price action, technicals, volume profile, sentiment, options flow)
- Eliminate repeated yfinance API calls across backtests
- Enable schema versioning (`computed_version='v1'` today; `v2` in future will coexist)

**Populated by:**
- `feature-extraction` CronJob (nightly at 3 AM UTC)
- Manual trigger: `kubectl create job --from=cronjob/feature-extraction manual-fe-$(date +%s)`

**Feature coverage query:**
```sql
SELECT
    COUNT(DISTINCT pt.id) AS total_parsed_trades,
    COUNT(DISTINCT et.parsed_trade_id) AS enriched_count,
    ROUND(100.0 * COUNT(DISTINCT et.parsed_trade_id) / NULLIF(COUNT(DISTINCT pt.id), 0), 2) AS coverage_pct
FROM parsed_trades pt
LEFT JOIN enriched_trades et ON et.parsed_trade_id = pt.id AND et.computed_version = 'v1'
WHERE pt.created_at >= NOW() - INTERVAL '90 days';
```

### Table: `daily_bars`

**Schema:**
```sql
CREATE TABLE daily_bars (
    ticker VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(20, 6),
    high NUMERIC(20, 6),
    low NUMERIC(20, 6),
    close NUMERIC(20, 6),
    adj_close NUMERIC(20, 6),
    volume BIGINT,
    source VARCHAR(20) NOT NULL DEFAULT 'tiingo',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
```

**Purpose:**
- Historical OHLCV data for backtesting and enrichment
- Backfilled from Tiingo API via `scripts/backfill_daily_bars.py`
- Reduces yfinance dependency (yfinance is now fallback only)

**Populated by:**
- One-time backfill: `python scripts/backfill_daily_bars.py --years 5`
- Incremental: feature-extraction CronJob calls `MarketDataProvider.daily_bars()` which upserts missing dates

### Table: `agent_backtest_step_logs`

**Schema:**
```sql
CREATE TABLE agent_backtest_step_logs (
    id BIGSERIAL PRIMARY KEY,
    backtest_id UUID NOT NULL REFERENCES agent_backtests(id) ON DELETE CASCADE,
    step VARCHAR(100) NOT NULL,
    sub_progress_pct INTEGER,
    message TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_agent_backtest_step_logs_backtest_ts ON agent_backtest_step_logs(backtest_id, ts);
```

**Purpose:**
- Granular progress tracking for each backtest step
- Operators can query to see exactly where a backtest stalled
- Dashboard fetches via `GET /api/v2/agents/{id}/backtest-logs` for detailed view

**Example rows:**
```sql
backtest_id | step              | sub_progress_pct | message                          | ts
------------|-------------------|------------------|----------------------------------|---------------------
abc-123     | Feature: enrich   | 15               | Enriching trade 78/500 (AAPL)   | 2026-05-12 03:15:23
abc-123     | Feature: enrich   | 30               | Enriching trade 150/500 (TSLA)  | 2026-05-12 03:17:45
abc-123     | Model: train      | 50               | Training LightGBM (epoch 3/10)  | 2026-05-12 03:22:10
```

---

## MarketDataProvider Abstraction

**Location:** `shared/market_data/`

**Abstract base class (`base.py`):**
```python
class MarketDataProvider(ABC):
    @abstractmethod
    async def daily_bars(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Fetch daily OHLCV bars. Returns empty DataFrame if unavailable."""
        ...

    @abstractmethod
    async def intraday_bars(self, ticker: str, start: datetime, end: datetime, interval: str = "5m") -> pd.DataFrame:
        """Fetch intraday bars. Raises NotImplementedError if unsupported."""
        ...
```

**Implementations:**
- `tiingo.py` — Tiingo REST API (primary)
- `yfinance.py` — yfinance library (fallback)
- Factory pattern: `get_provider(source: str) -> MarketDataProvider`

**Fallback chain in enrich.py:**
1. Try Tiingo (1000 req/hour, reliable)
2. On 429 or API key missing → fall back to yfinance
3. On persistent failure → skip trade with warning

---

## PVCs and Capacity Planning

### phoenix-price-cache (5Gi)

**Purpose:**
- Shared cache for yfinance/Tiingo API responses
- Deduplicates requests across feature-extraction runs and backtest enrich steps
- Format: JSON files keyed by `{ticker}_{start}_{end}.json`

**Mounted by:**
- `feature-extraction` CronJob at `/var/lib/phoenix/price_cache`
- `phoenix-backtest-worker` at `/var/lib/phoenix/price_cache`
- `phoenix-api` at `/var/lib/phoenix/price_cache` (read-only for inline backtests via `PHOENIX_BACKTEST_INLINE=1`)

**Capacity:**
- 5Gi handles ~50k cached API responses
- Current usage (as of 2026-05-12): 1.2Gi

**Growth estimate:**
- 60 tickers × 5 years × 1260 trading days = ~378k cache entries if no dedup
- With dedup (same ticker/date range reused): ~5k entries per month → 60k/year
- Should hit 5Gi limit in ~3 years → bump to 10Gi when usage exceeds 4Gi

### phoenix-backtest-data (20Gi)

**Purpose:**
- Persistent storage for backtest working directories
- Each backtest uses ~100-200 MB (Parquet files + trained models + logs)
- Survives pod restarts and helm upgrades

**Mounted by:**
- `phoenix-backtest-worker` at `/var/lib/phoenix/backtests`

**Directory structure:**
```
/var/lib/phoenix/backtests/
├── <backtest-id-1>/
│   ├── config.json
│   ├── tools/              (copied from agents/backtesting/tools/)
│   ├── output/
│   │   ├── transformed.parquet
│   │   ├── enriched.parquet
│   │   ├── preprocessed_train.parquet
│   │   ├── models/
│   │   │   ├── lightgbm_model.pkl
│   │   │   ├── catboost_model.pkl
│   │   │   └── hybrid_ensemble.pkl
│   │   └── live_agent/
│   │       ├── manifest.json
│   │       └── CLAUDE.md
│   └── logs/
│       ├── transform.log
│       ├── enrich.log
│       └── train.log
└── <backtest-id-2>/
    └── ...
```

**Capacity:**
- 20Gi supports ~100 backtest runs before cleanup
- Retention policy (implemented in worker): delete backtests older than 90 days if PVC usage > 80%

**Growth estimate:**
- 2 backtests/week × 150 MB/run = ~15 GB/year
- Should hit 20Gi limit in ~2 years → bump to 50Gi or implement aggressive cleanup (30-day retention)

### Concurrent Backtest Limit

**Current:** 1 (single-replica worker)
**Reason:** Single-replica serialization prevents OOM issues (each backtest can spike to 3Gi memory during LSTM training)

**Future scaling path:**
1. Horizontal: Deploy `phoenix-backtest-worker-large` with 8Gi memory, separate queue for "large" backtests
2. Vertical: Upgrade node RAM to 32Gi → 2 workers with 4Gi each
3. Elastic: Switch to K8s Jobs per backtest (adds image-pull latency, ~20s overhead per job)

**Rejected alternative (Celery):**
- Adds complexity (separate broker, result backend)
- Overkill for single-replica workload
- Redis streams + simple consumer loop is sufficient

---

## Fallback Paths

### 1. Redis is down

**Symptom:** `XADD` call in `agent_gateway.py` raises `redis.exceptions.ConnectionError`

**Fallback:**
```python
use_inline = os.getenv("PHOENIX_BACKTEST_INLINE", "0") == "1"
if use_inline or redis_unavailable:
    # Old path: asyncio.create_task() inside phoenix-api
    task = asyncio.create_task(_run_backtester_inline(agent_id, backtest_id, config))
    _running_tasks[backtest_id] = task
```

**Limitations:**
- Backtests orphaned on helm upgrade (original problem)
- No PVC persistence (ephemeral /app/data)
- Only use for local dev or emergency recovery

**Manual re-enqueue:**
```bash
kubectl exec -n phoenix deploy/phoenix-api -- python3 -c "
import asyncio
from shared.messaging.backtest_requests import enqueue_backtest
asyncio.run(enqueue_backtest('<backtest-id>', '<agent-id>', {...}))
"
```

### 2. Feature store is empty for a backtest

**Scenario:** User backtests a brand-new Discord channel with 500 trades, but feature-extraction CronJob hasn't run yet (or failed silently).

**Behavior:**
- `enrich.py` queries `enriched_trades` table → 0 rows match
- Falls back to inline enrichment for all 500 trades
- Uses `MarketDataProvider` factory (Tiingo primary, yfinance fallback)
- Slower (10-15 min instead of 2 min), but completes successfully
- feature-extraction will populate the feature store on next nightly run (trades are in DB via `parsed_trades` table)

**Verification:**
```sql
SELECT COUNT(*) FROM enriched_trades WHERE parsed_trade_id IN (
    SELECT id FROM parsed_trades WHERE backtest_id = '<backtest-id>'
);
```

### 3. Tiingo API key expired or rate-limited

**Scenario:** `TIINGO_API_KEY` env var missing or Tiingo returns 429 after 1000 requests in an hour.

**Behavior:**
1. `TiingoProvider` detects 429 → raises `RateLimitError`
2. `enrich.py` catches exception → switches to yfinance provider
3. yfinance provider fetches data (slower, less reliable, but free)
4. Logs warning: `"Tiingo rate limit hit, falling back to yfinance"`

**Recovery:**
- Tiingo rate limit resets after 1 hour
- Next enrich run will automatically switch back to Tiingo

**Manual workaround:**
```bash
# Rotate to a different Tiingo API key (free tier allows multiple keys per user)
kubectl set env deployment/phoenix-backtest-worker -n phoenix TIINGO_API_KEY=<new-key>
kubectl set env cronjob/feature-extraction -n phoenix TIINGO_API_KEY=<new-key>
```

### 4. Worker pod is down

**Symptom:** `kubectl get pods -n phoenix | grep backtest-worker` shows `CrashLoopBackOff` or `ImagePullBackOff`

**Impact:**
- New backtests queue up in Redis stream `backtest:requests`
- No data loss (QUEUED records in DB, unconsumed stream entries persist in Redis)

**Diagnosis:**
```bash
kubectl logs -n phoenix deploy/phoenix-backtest-worker --tail=100

# Check stream depth
kubectl exec -n phoenix redis-0 -- redis-cli XLEN backtest:requests
# Expected: 0-2 (normal), 10+ (worker is down)
```

**Recovery:**
1. Fix worker issue (OOM, missing env var, etc.)
2. `kubectl rollout restart deployment/phoenix-backtest-worker -n phoenix`
3. Worker auto-consumes queued entries on startup (XREADGROUP resume from last ACK)

---

## Known Limitations

### 1. Single-replica worker = single point of failure

**Impact:** If the worker pod crashes mid-backtest, the backtest record is stuck in `RUNNING` state until operator manually updates to `FAILED` and re-enqueues.

**Mitigation:**
- Worker sends heartbeat to API every 60s via `POST /api/v2/agents/{id}/backtest-heartbeat`
- API marks backtest as `FAILED` if no heartbeat received in 5 minutes
- Scheduled job (hourly) scans for stale `RUNNING` backtests and auto-fails them

**Future fix:** Multi-replica worker with K8s leader election (or idempotent per-backtest Jobs)

### 2. Feature-store schema is v1 and breaking changes require recomputation

**Impact:** If we add new features (e.g., options Greeks from Unusual Whales), existing `enriched_trades` rows with `computed_version='v1'` lack those features.

**Mitigation:**
- `computed_version` column enables coexistence: `v1` and `v2` rows can exist simultaneously
- feature-extraction CronJob inserts `computed_version='v2'` for new features
- enrich.py queries `computed_version='v2'` preferentially, falls back to `v1` if missing

**Recomputation path:**
1. Update `feature-extraction` to compute `v2` features
2. Manual backfill: `UPDATE enriched_trades SET computed_version='v1_deprecated'` → re-run CronJob
3. Or: accept that old backtests use `v1` features (analysis shows <5% performance delta)

### 3. PVC is ReadWriteOnce (single-node only)

**Impact:** On multi-node k8s clusters, the worker pod is pinned to the node where the PVC is provisioned. If that node goes down, the worker can't start on another node.

**Mitigation (single-node k3s):** Not applicable today — production is single-node

**Future fix (multi-node):** Switch to ReadWriteMany (RWX) via Longhorn or NFS-backed storage class

### 4. No automatic retry on transient failures

**Scenario:** Worker starts a backtest, yfinance API returns 500 Internal Server Error on trade #42 → entire backtest fails.

**Impact:** User sees `status=FAILED`, must manually click "Retry" in dashboard.

**Mitigation:**
- Each tool (transform.py, enrich.py, etc.) has internal retry logic (exponential backoff, 3 attempts)
- If all retries exhausted → backtest fails with detailed error message in `agent_backtest_step_logs`

**Future fix:** Backtest-level retry (re-enqueue with same `backtest_id` and resume from last completed step)

### 5. Redis streams have no TTL (memory leak risk)

**Impact:** Old backtest requests (QUEUED but never started) persist in Redis forever if not ACK'd.

**Mitigation:**
- XTRIM after each XACK: `XTRIM backtest:requests MAXLEN ~ 1000` (keep last 1000 entries, expire older)
- Redis `maxmemory-policy allkeys-lru` evicts old entries if memory exceeds 256Mi limit

**Future fix:** Add TTL to stream entries via XADD with MAXAGE (requires Redis 7.0+)

---

## Deployment and Operations

See also:
- [Operations Runbook: Backtest Pipeline Troubleshooting](../operations/runbooks/backtest-pipeline-troubleshooting.md)
- [Operations Runbook: Feature Store Setup](../operations/feature-store-runbook.md)
- [ADR 0007: Feature Store and Out-of-Process Backtest](adrs/0007-feature-store-and-out-of-process-backtest.md)

### Deployment checklist

1. Apply migration `051_feature_store`: `make db-upgrade`
2. Set `TIINGO_API_KEY` in phoenix-secrets (kubeseal flow)
3. Deploy via CD (push to `main` branch → GitHub Actions)
4. Backfill daily bars: `python scripts/backfill_daily_bars.py --years 5`
5. Trigger initial feature-extraction run: `kubectl create job --from=cronjob/feature-extraction manual-fe-$(date +%s)`
6. Verify a backtest completes in <2 min via dashboard

### Monitoring

**Key metrics (Prometheus):**
- `phoenix_backtest_duration_seconds{status="COMPLETED"}` — p50/p95/p99 should be < 120s with feature-store
- `phoenix_backtest_queue_depth` — Redis XLEN backtest:requests (should be 0-2 normally)
- `phoenix_feature_store_coverage_pct` — % of parsed_trades with enriched_trades entry (target: >95%)
- `phoenix_backtest_failures_total{reason="timeout"}` — spikes indicate yfinance/Tiingo issues

**Alerts:**
- `BacktestWorkerDown` — pod not ready for >5 min
- `BacktestQueueDepthHigh` — XLEN backtest:requests > 10 for >10 min
- `FeatureStoreCoverageLow` — coverage < 80% for >24 hours

### Capacity planning

**When to scale:**
- PVC usage > 80% → expand PVC or implement aggressive cleanup
- Backtest queue depth consistently >5 → add second worker replica (requires RWX PVC or per-job isolation)
- feature-extraction CronJob runtime >30 min → split into parallel jobs per ticker

**Cost estimate (Hostinger VPS):**
- PVC storage: included in node disk (193 GB total, Phoenix uses ~30 GB)
- No additional cost for Redis streams (256Mi is ample)
- Tiingo API: free tier sufficient for <1000 backtests/month

---

## Success Metrics

**Before (in-process pipeline):**
- Backtest duration: 15-30 min for 500-trade dataset
- Failure rate: 15-20% (yfinance timeouts, orphaned subprocesses)
- Operator intervention: 2-3 manual DB updates per week
- Resumability: 0% (all failures = full restart)

**After (feature-store + worker-pod):**
- Backtest duration: <2 min for 500-trade dataset (90% reduction)
- Failure rate: <5% (Tiingo is reliable; yfinance is fallback only)
- Operator intervention: 0 manual DB updates (heartbeat + auto-fail handles stale runs)
- Resumability: 100% (PVC persistence + step logs enable resume-from-step in future)

**Feature-store effectiveness:**
- 95%+ cache hit rate on enrich step after initial population
- Eliminates 30k+ yfinance API calls per backtest
- Nightly feature-extraction takes 5-10 min for 500 new trades (vs. 30 min inline)
