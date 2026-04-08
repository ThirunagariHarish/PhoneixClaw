# Changelog

All notable changes to Phoenix Trade Bot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
