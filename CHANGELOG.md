# Changelog

All notable changes to Phoenix Trade Bot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2026-05-04

**Infrastructure migration from Coolify to k3s + Helm — and first deploy live at https://cashflowus.com/.** Production now runs on a single-node k3s cluster (alongside selfagentbot) with declarative Helm charts, sealed secrets, cert-manager TLS, and automated CD via GitHub Actions.

### Added

- **Helm chart** (`helm/phoenix/`) — production-ready chart for k3s
  - 13 HTTP service Deployments + Services with httpGet liveness/readiness probes (phoenix-api, phoenix-dashboard, phoenix-ws-gateway, phoenix-llm-gateway, phoenix-broker-gateway, phoenix-execution, phoenix-discord-ingestion, phoenix-feature-pipeline, phoenix-inference-service, phoenix-agent-orchestrator, phoenix-prediction-monitor, phoenix-backtesting, edge-nginx)
  - phoenix-automation worker Deployment (no probes, no Service)
  - postgres and minio StatefulSets with persistent volume claims; redis Deployment
  - broker-gateway 100Mi PVC at `/app/data/.tokens` to persist Robinhood MFA session tokens across pod restarts
  - db-migrate Job as `post-install,post-upgrade` hook with `wait-for-postgres` initContainer that polls `postgres:5432` for up to 240s before running migrations
  - phoenix-config ConfigMap as `pre-install,pre-upgrade` hook with weight `-10` so it exists before db-migrate runs
  - k8s `Ingress` (class `traefik`) for `cashflowus.com` and `www.cashflowus.com` with `cert-manager.io/cluster-issuer: letsencrypt-prod` annotation
  - Bitnami SealedSecret template with 6 placeholder keys (POSTGRES_PASSWORD, JWT_SECRET_KEY, CREDENTIAL_ENCRYPTION_KEY, ANTHROPIC_API_KEY, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD)
  - argocd `Application` manifest at `helm/phoenix/argocd-application.yaml` for GitOps adoption (apply once images are in GHCR)
  - Chart.yaml, values.yaml, values.prod.yaml, README.md, ADR.md (7 decisions)
- **VPS provisioning script** (`infra/scripts/provision-k3s.sh`) — fresh-VPS bootstrap installing k3s, helm, sealed-secrets controller, cert-manager, ClusterIssuer `letsencrypt-prod`, and UFW firewall
- **Comprehensive deployment runbook** (`docs/operations/deployment-guide.md`) — operational procedures including image build/import, helm install with overrides, bootstrap admin user (PHOENIX_ADMIN_INVITE_CODE flow), traps to know about, disaster recovery

### Changed

- **CD pipeline** (`.github/workflows/cd.yml`) — rebuilt for k3s
  - On `v*` tag push: builds 14 Docker images, pushes to `ghcr.io/thirunagariharish/phoneixclaw/phoenix-<svc>`, SCPs the chart to the VPS, runs `helm upgrade --install --set image.tag=$TAG`
  - New required GitHub Actions secrets: `K3S_HOST`, `K3S_SSH_KEY`
  - Removed: `COOLIFY_WEBHOOK_URL`, `COOLIFY_TOKEN`, `COOLIFY_SSH_KEY`, `COOLIFY_HOST`
- **Documentation sweep** — Coolify references replaced with Helm/k3s across 16 files (README + 15 docs)
- **Service requirements.txt** — added `redis>=5.0.0` and `prometheus_client>=0.19.0` to `services/broker-gateway/requirements.txt`; added `prometheus_client>=0.19.0` to `services/discord-ingestion/requirements.txt`. These two services were the "pre-existing unhealthy containers" flagged in the cutover doc — root cause was missing transitive dependencies imported via `shared/utils/__init__.py` and `shared/observability/metrics.py`.
- **Agent Gateway OOM messaging** (`apps/api/src/services/agent_gateway.py`) — error message points to `helm/phoenix/values.yaml` (`resources.api.memory`) instead of docker-compose
- **DB migration script docstring** (`scripts/docker_migrate.py`) — references the Helm hook Job execution model

### Fixed (chart-level bugs caught during first deploy)

- **`DATABASE_URL` driver suffix** — every chart template that constructs DATABASE_URL now uses `postgresql+asyncpg://` (was bare `postgresql://`, which made sqlalchemy fall back to psycopg2 — not installed in service images — and crashed every pod with `ModuleNotFoundError: No module named 'psycopg2'`).
- **db-migrate hook ordering** — moved from `pre-install,pre-upgrade` (which ran before postgres existed; crashed with `socket.gaierror`) to `post-install,post-upgrade` with a `wait-for-postgres` initContainer that polls `postgres:5432` for up to 240s.
- **ConfigMap creation timing** — `phoenix-config` is now a `pre-install,pre-upgrade` hook with weight `-10`, so it exists before any pod (including the post-install db-migrate Job) tries to mount it via `envFrom`.
- **Probe types** — converted `livenessProbe.exec` (python urllib over HTTP) to `httpGet` for broker-gateway, feature-pipeline, inference-service, prediction-monitor (kubelet does HTTP probes natively; no need for python in the container).
- **edge-nginx DNS resolution** — removed Docker-style `resolver 127.0.0.11` from nginx.conf and switched proxy_pass targets to k8s service-cluster.local FQDNs (works at config-load time against k3s CoreDNS).

### Removed

- **Coolify deployment artifacts**
  - `docker-compose.coolify.yml` (462 lines)
  - `.env.coolify.example` (87 lines)
  - `scripts/coolify-deploy-via-ssh.sh`
  - `infra/scripts/provision-coolify.sh`
- **Legacy `RH_*` secrets in chart** — Robinhood, IB, Alpaca credentials are managed at runtime via the dashboard's Connectors panel and stored encrypted in the `connectors` table; not chart-level secrets. SealedSecret reduced from 9 → 6 keys.

### Operator action required

1. **Provision k3s** (one-time): run `infra/scripts/provision-k3s.sh` on the VPS for k3s + helm + sealed-secrets + cert-manager + ClusterIssuer + UFW
2. **GitHub Actions secrets** at https://github.com/ThirunagariHarish/PhoneixClaw/settings/secrets/actions:
   - Add: `K3S_HOST`, `K3S_SSH_KEY`
   - Remove: `COOLIFY_WEBHOOK_URL`, `COOLIFY_TOKEN`, `COOLIFY_SSH_KEY`, `COOLIFY_HOST`
3. **Seal production secrets** (one-time): for each of the 6 keys, run `echo -n "$VALUE" | kubeseal --raw --namespace phoenix --name phoenix-secrets`. Paste ciphertexts into `helm/phoenix/templates/sealedsecret.yaml.template`, save as `sealedsecret.yaml`, commit. (See `helm/phoenix/README.md` for the full workflow.)
4. **First-time install** (until images are pushed to GHCR): `helm install phoenix helm/phoenix/ -f helm/phoenix/values.prod.yaml -n phoenix --create-namespace --set image.repository=phoenix --set image.tag=local --set image.pullPolicy=IfNotPresent`. The `--set` overrides are required because values.prod.yaml's `ghcr.io/thirunagariharish/phoneixclaw/phoenix-X:latest` images don't exist yet — push them via a `v*` tag to enable CD.
5. **Bootstrap admin user**: see §7 of `docs/operations/deployment-guide.md`.

---

## [2.0.0] - 2026-04-19

**MAJOR RELEASE** — Breaking changes require migration steps. See [docs/releases/v2.0.0.md](docs/releases/v2.0.0.md) for full release notes and migration guide.

### Added

- **Phase A: Pipeline Engine**
  - Pipeline-based execution engine with Redis Streams orchestration
  - Robinhood MCP broker adapter with session persistence and zero-latency restore
  - IBKR Gateway broker adapter with daily re-auth flow
  - `engine_type` field on `agents` table (values: `pipeline`, `legacy`)
  - Database migrations 046-048 for pipeline engine support
  - Kill-switch endpoint `POST /api/v2/agents/kill-switch` for emergency agent shutdown

- **Phase B: Observability**
  - Grafana dashboard for agent wake-flow monitoring (`infra/observability/grafana/agent-wake-flow.json`)
  - Prometheus metrics: agent lifecycle states, broker circuit breaker states, Redis stream lag
  - Structured JSON logging with request IDs and trace context
  - Heartbeat monitoring with `last_activity_at` tracking

- **Phase C: Backtesting Database Persistence**
  - `agent_backtest_artifacts` table for storing backtest metrics, model files, and evaluation reports
  - Historical comparison UI for p50/p95 latency trends across backtest runs
  - Reproducibility tags: git SHA, Python version, dependency snapshot

- **Phase D: Dashboard UX**
  - Redesigned agent detail page with 10-tab layout (Trades, Backtesting, Skills, Logs, Config, etc.)
  - Decision trail visibility: eye icon expands full `decision_trail` JSON for every trade
  - Real-time SSE streaming for agent logs and trade feed

- **Phase E: Go-Live Hardening**
  - Signal-to-trade latency benchmark (`tests/benchmark/test_signal_to_trade_latency.py`)
  - Security findings template (`docs/dev/security-findings-phase-e.md`)
  - Staged rollout plan (`docs/operations/go-live-rollout-plan.md`)
  - Observability checklist (`docs/operations/go-live-observability.md`)
  - 8 operational runbooks under `docs/runbooks/`

### Changed

- **BREAKING:** `POST /api/v2/agents` now requires `engine_type` field (`pipeline` or `legacy`)
- **BREAKING:** `go-live-regression` Makefile target no longer includes `test-bridge`
- Agent lifecycle state machine extended with `backtesting_approved` state
- `agent_trades.decision_trail` now stored as JSONB (migration 038)
- Go-live regression checklist updated with PM / QA / Eng Lead / Security Lead sign-off lines

### Fixed

- Backtester OOM crashes (memory limits raised from 512M to 2G, fail-fast on SIGKILL)
- Robinhood suspicious-login loop (session pickle persistence instead of re-login on every trade)
- Agent creation wizard connector validation for non-trading agent types
- Paper-mode safety gaps (dedicated template, no credentials injected into paper agents)

### Removed

- **BREAKING:** OpenClaw Bridge Service (`openclaw/bridge/` directory deleted)
  - All `/api/v2/bridge/*` endpoints removed
  - Makefile targets `run-bridge` and `test-bridge` removed
  - Environment variable `BRIDGE_TOKEN` no longer used
- **BREAKING:** Alpaca broker adapter (`shared/broker_adapters/alpaca.py` removed)

### Migration Steps

See [docs/releases/v2.0.0.md](docs/releases/v2.0.0.md) for detailed migration guide. Summary:

1. Backup database: `pg_dump -U postgres phoenix_trade_bot > backup_v1.15.3.sql`
2. Remove `BRIDGE_TOKEN` from `.env`
3. Add `ROBINHOOD_MCP_URL` and `IB_GATEWAY_HOST` (if using pipeline engine)
4. Run migrations: `make db-upgrade`
5. Update existing agents: `UPDATE agents SET engine_type = 'legacy' WHERE engine_type IS NULL;`
6. Rebuild: `docker compose up -d --build`

### Rollback

Full rollback instructions in [docs/releases/v2.0.0.md](docs/releases/v2.0.0.md) §Rollback Plan.

---

## [1.15.4] - 2026-04-12 — Fix Robinhood Suspicious-Login / Session Revocation Bug

**Patch release.** Eliminates the "suspicious login detected" Robinhood push
notifications that fired on every trade execution and Discord message, blocking
millisecond-latency trade paths. Three coordinated root causes are resolved: the
context fetcher no longer revokes the shared session on every portfolio poll; the MCP
subprocess now restores a persisted session pickle via a zero-network fast-path instead
of calling `rh.login()` fresh on every invocation; and the session pickle is written to
the agent's persistent work directory instead of the ephemeral Docker `/root` overlay.
One commit; all existing tests green.

### Fixed

- **`apps/api/src/services/robinhood_context_fetcher.py`** — Removed the
  `rh.authentication.logout()` call that executed after every portfolio fetch inside
  `_fetch_sync()`. This call was revoking the shared OAuth token used by the live
  agent's MCP server, triggering Robinhood's suspicious-device-approval flow on the
  next login attempt.
- **`agents/templates/live-trader-v1/tools/robinhood_mcp.py`** — Added
  `_try_restore_session_from_pickle()` zero-network fast-path: the subprocess now
  restores an existing session from the persisted pickle before falling back to a full
  `rh.login()`. `HOME` is self-corrected to the agent's persistent work-dir on startup
  so the pickle survives container restarts. Re-auth on HTTP 401 is now handled inside
  `_retry()` with a thread-local guard to prevent recursive re-auth loops. No-MFA
  fallback login retries reduced from 3 to 1 (was generating up to 6 push notifications
  per trade execution). `.tokens/` directory created with `chmod 0700`; chmod failures
  are logged as warnings rather than silently suppressed.
- **`agents/templates/live-trader-v1/tools/robinhood_mcp_client.py`** — `HOME` is now
  explicitly set to the agent work-dir in the subprocess environment so the MCP server
  and its client agree on the pickle location across all launch paths.

## [1.15.3] - 2026-04-08 — Live Portfolio Context & MCP Tools in Agent Chat

**Patch release.** Chat sessions for live agents (status `RUNNING` / `APPROVED`) now
receive real-time Robinhood portfolio data injected into `agent_context.json` and a
curated set of read-only Robinhood MCP tools, so agents can answer questions about
current positions and account balance without saying "I have no Robinhood connection."
Also fixes `_ensure_system_agent` to include `created_at`/`updated_at` columns in the
idempotent INSERT, preventing `NOT NULL` constraint failures on strict DB schemas, and
canonicalises system-agent display names via a new `_SYSTEM_AGENT_NAMES` dict.
One commit; 8 new tests added; all existing tests green. Cortex APPROVED.

### Added

- **`apps/api/src/services/chat_responder.py`** — Live portfolio context injection for
  live agents: `RobinhoodContextFetcher` is called at the start of every chat turn for
  agents with status `RUNNING` or `APPROVED`; the result (positions, account value,
  buying power, cash) is merged into `agent_context.json` under the `live_portfolio`
  key. On fetch failure, an `{"error": "…"}` stub is written so the agent acknowledges
  the connection attempt rather than claiming no data exists.
- **`apps/api/src/services/chat_responder.py`** — Read-only Robinhood MCP tools wired
  into live-agent chat sessions: `_write_claude_settings()` is called from
  `_prepare_workdir()` when live credentials are present, and `robinhood_mcp.py` is
  copied into `tools/`. Eight read-only tools exposed:
  `robinhood_login`, `get_positions`, `get_account`, `get_quote`,
  `get_account_snapshot`, `get_nbbo`, `get_watchlist`, `get_order_status`.
  Order-placement tools are intentionally excluded.
- **`apps/api/src/services/chat_responder.py`** — `_build_prompt()` gains
  `has_live_portfolio` and `has_mcp_tools` flags that inject instructional sections
  into the system prompt, directing the agent to use live data and MCP tools when
  available.

### Fixed

- **`apps/api/src/services/agent_gateway.py`** — `_ensure_system_agent` INSERT now
  includes `created_at` and `updated_at` columns (`NOW(), NOW()`), preventing
  `NOT NULL` constraint violations on databases where those columns carry no
  server-side default.
- **`apps/api/src/services/agent_gateway.py`** — New `_SYSTEM_AGENT_NAMES` dict maps
  `agent_type` keys to their canonical display names (e.g. `"eod_analysis"` →
  `"EOD Analysis Agent"`), replacing the fragile `.replace("_", " ").title()` fallback.
  Names now match the seed list in `main.py` exactly.
- **`apps/api/src/services/agent_gateway.py`** — `sys` import promoted to module
  level (was deferred as `import sys as _sys` inside `_write_claude_settings`); all
  `claude_agent_sdk` and `shared.triggers` imports sorted alphabetically (ruff I001).

### Tests

- **`apps/api/tests/test_robinhood_mcp_wiring.py`** — 8 new tests:
  `test_write_claude_settings_allows_mcp_tools`, `test_write_claude_settings_uses_sys_executable`,
  `test_write_claude_settings_paper_mode_no_credentials_in_env`,
  `test_write_claude_settings_live_mode_has_credentials_in_env`,
  `test_heal_missing_settings_paper_agent_gets_mcp_entry`, and three additional
  assertions on existing helpers. **Behaviour change:** paper-mode agents now always
  receive an MCP entry (`PAPER_MODE=true`, no real credentials);
  `test_write_claude_settings_without_credentials` updated accordingly.
- **`tests/unit/test_agent_gateway_error_path.py`** — Import order corrected (ruff I001).

### Rollback

No database migrations in this release. To roll back:

```bash
# 1. Return to the commit immediately before this release (last clean v1.15.2 state)
git checkout 2ac7ad1

# 2. Rebuild and restart the API service
docker compose up -d --build phoenix-api
```

> **Note:** Rolling back disables live portfolio context injection and MCP tools in
> chat. Agents will fall back to static context only and will no longer report live
> positions or account data during chat sessions.

---

## [1.15.2] - 2026-04-07 — Agent-Gateway FK Guard for System Agents

**Patch bug fix.** Clicking "Morning Briefing" in the dashboard raised a
`ForeignKeyViolationError` whenever the startup seed had not created the reserved
system-agent rows (DB not ready at boot, schema drift, or dev wipe). The fix adds a
self-healing `_ensure_system_agent()` helper that guarantees the row exists immediately
before every `AgentSession` INSERT — with no dependency on seed-time success.
One commit (`2ac7ad1`); 5 new tests passing; 791/791 existing unit tests green. No regressions.

### Fixed

- **`apps/api/src/services/agent_gateway.py`** — New `_ensure_system_agent(db, agent_id, name)`
  helper executes an idempotent `INSERT … ON CONFLICT (id) DO NOTHING` in the **same**
  DB session, immediately before every `AgentSession` INSERT that uses a reserved UUID.
  Applied to all five system-agent creation paths:
  - `create_supervisor_agent()` — UUID `_SUPERVISOR_AGENT_UUID` (slot 1)
  - `create_morning_briefing_agent()` — UUID `_MORNING_BRIEFING_AGENT_UUID` (slot 2) ← reported crash site
  - `_spawn_one_shot_agent()` — UUIDs `_EOD_ANALYSIS_AGENT_UUID` / `_DAILY_SUMMARY_AGENT_UUID` /
    `_TRADE_FEEDBACK_AGENT_UUID` (slots 3–5, same structural flaw pre-emptively patched)
- **`apps/api/src/services/agent_gateway.py`** — Five hardcoded UUID strings promoted to
  named module-level constants (`_SUPERVISOR_AGENT_UUID` … `_TRADE_FEEDBACK_AGENT_UUID`);
  a future typo now raises `NameError` at import time rather than a silent FK violation at
  runtime. `sqlalchemy.text` import moved to module level (was deferred).
- **`tests/unit/test_agent_gateway_error_path.py`** — NEW: 5 unit tests in
  `TestEnsureSystemAgent` and `TestSpawnOneShotAgentFKGuard`:
  - `_ensure_system_agent` issues exactly one `execute()` call with the correct UUID and
    agent name in the `INSERT ON CONFLICT` params.
  - `_spawn_one_shot_agent` calls `_ensure_system_agent` **before** `db.add(AgentSession)`.
  - Execution order verified: guard runs prior to the FK-constrained INSERT.
  All 5 new tests pass.

### Root Cause

`create_morning_briefing_agent()` (and the other four system-agent paths) assumed that
`_seed_system_agents()` in `main.py` had already populated the five reserved rows on
startup. That seed swallows all exceptions — if it failed for any reason the app
continued silently, leaving `agents` rows absent. The next dashboard click triggered
`agent_sessions_agent_id_fkey` FK violation on `agent_id = 00000000-0000-0000-0000-000000000002`.

### Rollback

No database migrations in this release. To roll back:

```bash
# 1. Revert to the previous release tag
git checkout v1.15.1

# 2. Rebuild and restart the API service
docker compose up -d --build phoenix-api
```

> **Note:** Rolling back re-exposes the FK violation for any environment where
> `_seed_system_agents` did not run successfully at boot. Ensure the seed completes
> cleanly before reverting, or manually INSERT the five system-agent rows.

---

## [1.15.1] - 2026-04-08 — Robinhood MCP Server Wiring Fix

**High-severity bug fix.** Live agents were provisioned without a `.claude/settings.json`
file, meaning the Claude SDK had no awareness of the Robinhood MCP server. As a result,
agents could neither add symbols to the watchlist nor execute trades via MCP.
Two commits; 6/6 acceptance criteria PASS; 0 regressions. Cortex APPROVED. Quill green.

### Fixed

- **`apps/api/src/services/agent_gateway.py`** — New `_write_claude_settings()` helper
  that writes `.claude/settings.json` into every agent working directory, listing the
  Robinhood MCP server with credentials injected as environment variable references.
  File is `chmod 0o600` (owner-read/write only). Helper is called after `config.json`
  write in `_prepare_analyst_directory()`, `create_position_agent()`, and
  `create_specialized_agent()`.
- **`apps/api/src/main.py`** — New `_heal_live_agent_claude_settings()` startup healer
  that iterates all existing live agent directories and back-fills any missing
  `.claude/settings.json` on service start. Wired into `lifespan()` before agent
  recovery so previously-provisioned agents are corrected automatically on next deploy.
  Healer delegates to `_write_claude_settings()` (no logic duplication).
- **`apps/api/tests/test_robinhood_mcp_wiring.py`** — NEW: 6 unit tests covering
  settings-file creation, correct path construction, env-var credential injection,
  `chmod 0o600` enforcement, healer back-fill logic, and position-agent `paper_mode`
  inheritance. All 6 passing.

### Code-Review Fixups (commit `bcb6d69`)

- **B1** — Corrected path hops in startup healer (was navigating one level too deep).
- **M1** — `chmod` tightened from `0o644` → `0o600`.
- **M2** — Healer delegates to `_write_claude_settings()` instead of duplicating the
  JSON-assembly logic inline.
- **M3** — Integration test upgraded from mock-only to a real end-to-end fixture.
- **S1** — `create_position_agent()` now correctly propagates `paper_mode` to the
  spawned agent subprocess.

### Rollback

No database migrations in this release. To roll back:

```bash
# 1. Revert to the previous release tag
git checkout v1.15.0

# 2. Rebuild and restart the API service
docker compose up -d --build phoenix-api

# 3. Existing .claude/settings.json files written by the healer are inert on the
#    older codebase — they can be left in place or removed manually:
#    find agents/ -name "settings.json" -path "*/.claude/*" -delete
```

> **Note:** Rolling back means live agents will again lack MCP awareness until the
> fix is re-applied. Plan a maintenance window or route trade execution via the
> REST fallback during the rollback window.

---

## [1.15.0] - 2026-04-08 — Prediction Markets (Phase 15)

A complete **Prediction Markets** feature built across 8 implementation sub-phases,
introducing autonomous AI bet-scoring agents, a full LLM scorer chain, 20 new API
endpoints, 7 new DB tables, two venue adapters (paper mode only), and a redesigned
dashboard tab with real-time SSE chat and live agent logs.
Cortex APPROVED on all 8 phases. Quill regression green.

### Added

- **Prediction Markets** tab (renamed from Polymarket) with Robinhood Predictions
  as primary venue (paper mode; no real money at risk)
- **TopBetsAgent** — 24/7 autonomous agent scoring prediction markets on a 60-second
  cycle; Redis heartbeat; orchestrator-registered (`agents/polymarket/top_bets/`)
- **AI Scorer Chain** — four-stage pipeline:
  1. `ReferenceClassScorer` — historical base-rate lookup via embedding similarity
  2. `CoTSampler` — N=5 parallel LLM chain-of-thought calls for self-consistency
  3. `DebateScorer` — Bull vs Bear argument generation + LLM Judge adjudication
  4. `LLMScorer` weighted blend + `TopBetScorer` confidence gating + `ModelEvaluator`
- **VenueSelector** pill component + **TopBetsPanel** with per-bet confidence bars
  and expandable AI-reasoning cards (`apps/dashboard/src/pages/polymarket/`)
- **Chat tab** (8th dashboard tab) — SSE streaming chat with full prediction-market
  context; messages persisted to `pm_chat_messages`
- **Logs tab** (9th dashboard tab) — agent health monitoring, real-time activity
  log, manual cycle-trigger button; backed by `pm_agent_activity_log`
- **AutoResearchAgent** — daily nonce-gated agent: category identification +
  research query generation; findings stored in `pm_strategy_research_log`
- **20 new API endpoints** across 6 route modules:
  `pm_top_bets`, `pm_chat` (SSE), `pm_agents`, `pm_research`, `pm_venues`,
  `pm_pipeline`
- **7 new DB tables** (Alembic migration 033):
  `pm_top_bets`, `pm_chat_messages`, `pm_agent_activity_log`,
  `pm_strategy_research_log`, `pm_historical_markets`, `pm_market_embeddings`,
  `pm_model_evaluations`
- **RobinhoodPredictionsVenue** + **PolymarketVenue** adapters — paper mode only;
  `place_order(paper=False)` raises `ValueError` unconditionally in both adapters
- **HistoricalIngestPipeline** + **EmbeddingStore** — SHA-256 hash deduplication
  fallback (no pgvector dependency required)
- **Docker service `pm-top-bets-agent`** — opt-in via `--profile agents`; does not
  start with plain `docker compose up`; all credentials injected from env
- **`TopBetsConfig`** dataclass for agent tuning; schema safety net via
  `_ensure_prod_schema()` on startup
- **`VenueRegistry`** — pluggable multi-venue dispatch layer
- **.env.example** updated with `PM_TOP_BETS_*` and `PM_RESEARCH_ENABLED` keys

### Changed

- `apps/dashboard/src/pages/polymarket/index.tsx` — tab label renamed from
  "Polymarket" to "Prediction Markets"; `JurisdictionBanner` styling updated to
  blue/info tone; tab grid extended for Chat (8th) and Logs (9th) tabs
- `services/orchestrator` — TopBetsAgent and AutoResearchAgent registered in the
  orchestrator lifecycle

### Database

- **`033_pm_phase15`** (down_revision `032`) — creates all 7 prediction-markets
  tables. Fully reversible via `alembic downgrade 032`. No destructive changes to
  existing tables.

### Known Limitations

- **Paper mode only** — live trading on Robinhood Predictions and Polymarket is
  blocked at the adapter layer; promotion to live trading deferred to a future phase.
- **No pgvector** — embedding similarity uses in-process cosine distance with a
  SHA-256 hash deduplication cache; pgvector ANN index deferred to Phase 16.
- **Single-venue scoring** — TopBetsAgent scores one venue per cycle; cross-venue
  arbitrage deferred.
- `scan_options_flow` in the Analyst Agent tool suite remains a placeholder
  (carried from v0.5.0).

### Rollback

```bash
# 1. Downgrade DB migration (drops all 7 pm_phase15 tables)
alembic downgrade 032

# 2. Stop the agent Docker service (if running)
docker compose --profile agents stop pm-top-bets-agent

# 3. Revert to previous image / git tag
git checkout v0.5.0

# 4. Rebuild and restart
docker compose up -d --build
```

---

## [0.5.0] — 2026-04-07 — Analyst Agent (Phase 1)

Introduces the **Analyst Agent** — a new agent type with 6 configurable analyst
personas, a full tool suite (chart analysis, options flow, news sentiment, trade
setup scoring, signal emission), an orchestrated trading workflow, 3 new API
endpoints, and a persona picker + signal-feed dashboard. Includes DB migration
034 (merge migration) adding 7 new columns to `trade_signals`. Python 3.9
SQLAlchemy `Mapped[X | None]` compatibility fixed across 25 model files.
Cortex APPROVED, Quill 17/17 tests passing, 0 regressions.

### Added

- **Analyst Agent (Phase 1)** — New `analyst` agent type with 6 configurable personas
  - **Personas**: `aggressive_momentum`, `conservative_swing`, `options_flow_specialist`,
    `dark_pool_hunter`, `sentiment_trader`, `scalper` (defined in `agents/analyst/personas/library.py`)
  - **Tools**: chart analysis (RSI/MACD/Bollinger Bands/VWAP/pattern detection),
    options flow scanner, news sentiment (FinBERT-powered), trade setup scorer,
    signal emitter (`agents/analyst/tools/`)
  - **Orchestrated workflow**: signal intake → technical confirmation → sentiment
    cross-check → confidence scoring → trade decision → signal emission
  - **New API endpoints**:
    - `POST /api/v2/agents/{id}/analyst/run` — run analyst workflow for an agent
    - `GET /api/v2/agents/{id}/signals` — retrieve per-agent trade signals
    - `GET /api/v2/signals` — retrieve all trade signals (global feed)
  - **Dashboard**: `PersonaSelector.tsx` in the 4-step agent creation wizard;
    `AnalystSignalCard.tsx` and `AnalystSignalFeed.tsx` for the signal feed
  - **17 unit tests** across `test_analyst_scorer.py`, `test_analyst_personas.py`,
    `test_emit_trade_signal.py`, `test_analyst_routes.py` — all passing

### Changed

- Agent `type` field now accepts `analyst` in addition to `trading`, `trend`,
  `sentiment` — validation pattern updated in `apps/api/src/routes/agents.py`
- `apps/api/src/services/agent_gateway.py` — added `create_analyst_agent()` method
  and `ANALYST_TEMPLATE` constant
- `apps/dashboard/src/pages/Agents.tsx` — 4-step wizard with persona picker
- `shared/db/models/trade_signal.py` — 7 new analyst-specific columns:
  `analyst_persona`, `tool_signals_used`, `risk_reward_ratio`, `take_profit`,
  `entry_price`, `stop_loss`, `pattern_name`
- **Python 3.9 SQLAlchemy compatibility fix**: `Mapped[X | None]` → `Mapped[Optional[X]]`
  applied across 25 model files (`shared/db/models/`)

### Database Migrations

- `034_add_analyst_agent.py` — Merge migration resolving multi-head chain
  (`09b0dd176f5d` + `033_pm_phase15` → `034`). Adds 7 new nullable columns to
  `trade_signals`; updates `agents.type` CHECK constraint to include `'analyst'`.
  Fully reversible (`alembic downgrade 033_pm_phase15`). Idempotent `_has_column()`
  guard on all `ADD COLUMN` operations.

### Known Limitations (Phase 1)

- `scan_options_flow` tool is a placeholder — live dark-pool feed integration
  deferred to Phase 2.
- No live trading execution — analyst agent emits signals only; execution
  routing is Phase 2.
- No scheduler — analyst run must be triggered via API; cron/APScheduler wiring
  is Phase 2.

---

## [0.4.0] — 2025-07-14 — Skills / Tools Tab

New read-only "Skills" tab on each live agent's detail page, surfacing the
agent's full tool and skill manifest without any backend changes.
1 new file, 1 modified file, zero TypeScript errors. Cortex APPROVED,
Quill 18/19 green (1 P3 informational deviation, acknowledged).

### Added

- **Skills / Tools tab** (`/agents/:id` → 10th tab "Skills") powered by
  `AgentSkillsTab.tsx` — displays tools, skills, MCP servers, and
  character/identity info sourced from the existing
  `GET /api/v2/agents/:id/manifest` endpoint. No new API routes or DB
  migrations required.
  - **Tools panel** — name, description, category badge, active/inactive
    indicator for each tool in the agent manifest.
  - **Skills panel** — name, description, category badge for each skill.
  - **MCP Servers panel** — inferred from agent config; Robinhood MCP with
    Paper/Live badge.
  - **Character & Identity panel** — agent character type, analyst, channel,
    active mode.
- `Wrench` icon imported from `lucide-react` for the Skills tab trigger.

### Changed

- `AgentDashboard.tsx` (`LiveSection`): tab grid expanded from `grid-cols-9`
  to `grid-cols-10`; `TabsTrigger` + `TabsContent` added for `value="skills"`.

### Known limitations

- Manifest data is read-only; editing tools/skills from the UI is deferred.
- `AgentSkillsTab` query key uses codebase convention (minor deviation from
  spec typo, P3 informational — no user-facing impact).

## [0.3.0] — 2026-04-08 — Agents Tab Bug-Fix + Pipeline Hardening

Bug-fix and hardening release resolving P0 signal pipeline failures, agent
creation wizard regressions, paper-mode safety gaps, and a set of backend
error-handling deficiencies. Includes new paper-trading agent infrastructure
(template, cursor persistence, log tool) and `error_message` API surface.
7 commits, Cortex APPROVED, Quill regression green (12/12 ACs, BUG-001/002/003 resolved).

### Fixed

#### Agent creation wizard (Agents Tab)
- `computeCanAdvance()` now correctly allows non-trading agent types (trend,
  sentiment, news) to advance step 0 without a connector; trading type guard
  preserved unchanged.
- `AgentBacktest` row created with `status="PENDING"`, transitions to
  `"RUNNING"` when backtesting actually begins — eliminates AC1.3.2 race
  condition. Active-backtest query updated to include `PENDING` status.
- `_mark_backtest_failed()` sets agent `status="ERROR"` (was `"CREATED"`),
  preventing silent revert to creatable state after failure.
- `_mark_backtest_completed()` clears `error_message = None` on success.
- All stale `discord_listener.py` references replaced with
  `discord_redis_consumer.py` across slash commands, skills, manifests, and
  `create_live_agent.py`.

#### Paper trading pipeline (P0)
- **Critical**: `live_pipeline.py` was reading from an in-process queue always
  empty in production. Replaced with `_redis_signal_stream()` reading Redis
  Streams via `stream:channel:{connector_id}`.
- `discord_redis_consumer.py` fully rewritten: stream key from `connector_id`;
  cursor persisted as flat `stream_cursor.json`; SIGTERM/SIGINT handler;
  exponential backoff (up to 30s); 500-entry stream trim; 30s hard deadline
  removed.
- Heartbeat endpoint: removed duplicate shadow handler; `last_activity_at` now
  updates on every heartbeat. `HeartbeatBody` extended with optional
  `signals_processed`, `trades_today`, `timestamp` fields.
- `message_ingestion.py`: DB write failures now raise (not swallowed); Redis
  publish gated on DB success.
- Feed endpoint filters to `is_active=True` connector agents only.

#### Inference
- `inference.py`: graceful fallback from PyTorch `.pt` to sklearn `.pkl` when
  class definitions unavailable; raises `FileNotFoundError` with clear message
  when neither file exists (was silently returning `SKIP` / confidence 0).

### Added

- `agents.error_message TEXT NULL` — stores latest agent error (migration 032).
- `agent_sessions.trading_mode VARCHAR(20) DEFAULT 'live'` (same migration).
- `AgentResponse.error_message` field — API surfaces error text; dashboard
  renders red error banner on agent cards when `status=ERROR`.
- `STATUS_CONFIG.ERROR` red badge on the dashboard.
- `CLAUDE.md.paper.jinja2` — dedicated paper-trading template with explicit
  `⛔ PROHIBITIONS` block; paper agents never receive broker credentials.
- `log_paper_trade.py` — paper trade logging tool; appends to
  `paper_trades.json`; zero broker calls.
- `config.json` generation injects `connector_id` and `paper_mode`; Robinhood
  credentials withheld from paper agents.
- `live_pipeline.py` EXECUTE stdout now gated on `not paper_mode`.

### Database

- Migration `032_agents_tab_fix.py` (down_revision 031) — additive only,
  idempotent `_has_column()` guard, fully reversible (`alembic downgrade 031`).

### Known limitations

- `POST /api/v2/agents/{id}/retry` not yet implemented; UI shows disabled
  placeholder. Tracked for v0.3.1.
- `discord_listener_DEPRECATED.py` still ships in template dir; deletion
  deferred to v0.3.1.
- `_db_write_failures` counter is in-process only (resets on restart);
  Prometheus wiring deferred to v0.3.1.

---

## [0.2.0] — 2026-04-07 — Polymarket Tab v1.0

First-class support for Polymarket prediction-market trading, delivered as a new
top-level tab in the dashboard with its own agent runtime, connector, data
pipeline, and risk controls. 15 implementation phases, 215+ tests, Cortex
APPROVED, Quill regression green (BUG-1, BUG-2 resolved).

### Added — Polymarket Tab (v1.0 scope)

- **F1 — Venue connector & market discovery**: Polymarket REST/WS connector under
  `services/connector-manager/src/brokers/polymarket/` with discovery service and
  venue registry entry. Kalshi left as a stub for v1.1.
- **F2 — Market data ingestion**: Order-book and trade collectors under
  `services/message-ingestion/src/collectors/`, TimescaleDB-backed storage via
  migrations `029_pm_v1_0_initial`, `030_pm_paper_mode_since`,
  `031_pm_last_backtest_at`.
- **F3 — Polymarket agent runtime**: Dedicated runtime
  (`services/orchestrator/src/pm_agent_runtime.py`) and agent template under
  `agents/polymarket/` integrated with the existing agent lifecycle state
  machine.
- **F9 — Paper-mode-by-default**: New Polymarket agents start in paper mode and
  require an explicit user-signed attestation + promote flow before any live
  capital is deployed.
- **F10 — Risk chain integration**: Polymarket positions flow through the
  existing 3-layer risk chain (agent → execution → global) with
  prediction-market-specific guards in `services/execution/src/risk_chain.py`.
- **F12 — Backtesting loader**: Historical Polymarket loader under
  `services/backtest-runner/src/loaders/` plus unit + benchmark coverage
  (`tests/benchmark/test_pm_book_latency.py`,
  `tests/benchmark/test_pm_scan_throughput.py`).
- **F13 — Dashboard tab & morning briefing**: New Polymarket pages under
  `apps/dashboard/src/pages/polymarket/`, API routes in
  `apps/api/src/routes/polymarket.py`, and a Polymarket section in the morning
  briefing agent (`agents/templates/morning-briefing-agent/tools/compile_pm_section.py`).

### Database

- `029_pm_v1_0_initial` — core Polymarket tables
- `030_pm_paper_mode_since` — paper-mode timestamping for promotion gating
- `031_pm_last_backtest_at` — last-backtest tracking for readiness checks

### Tests

- 215+ new tests across `tests/unit/polymarket/`,
  `tests/integration/polymarket/`, `tests/chaos/`, plus
  `apps/api/tests/test_polymarket_routes.py`, `tests/unit/test_migration_031.py`,
  and `tests/unit/test_morning_briefing_pm_section.py`.

### Deferred to v1.1+

The following features were de-scoped from v1.0 and are tracked for a later
release:

- **F4** — Multi-venue arbitrage across Polymarket + Kalshi
- **F5** — Advanced limit-order management (iceberg, post-only laddering)
- **F6** — Cross-market correlation signals
- **F7** — LLM-driven event resolution monitoring
- **F8** — Automated hedging via options overlay
- **F11** — Social-sentiment ingestion for prediction markets

### Fixed (bundled)

- **Backtester OOM**: `phoenix-api` container memory raised from 512M to 2G,
  `NODE_OPTIONS` capped to prevent V8 heap runaway, `WEB_CONCURRENCY=2` to bound
  Uvicorn workers, and fail-fast handling for exit-code -9 (SIGKILL/OOM) in
  `apps/api/src/services/agent_gateway.py`. See `docker-compose.coolify.yml` and
  `apps/api/entrypoint.sh`.

### Known limitations

- Single-venue (Polymarket only); Kalshi adapter is a stub.
- US-jurisdiction disclaimer applies — see `docs/LEGAL.md`.
- Live trading requires manual attestation + promote; no auto-promotion.

## [0.1.0] — Initial platform release

Initial Phoenix Trade Bot platform: multi-tenant API, dashboard, agent
orchestrator, Alpaca/IBKR execution, backtesting pipeline, morning briefing.
