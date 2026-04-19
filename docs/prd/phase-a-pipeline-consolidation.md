# PRD: Phase A — Pipeline Engine Consolidation + Multi-Broker Support

Version: 1.0 | Status: Draft | Date: 2026-04-18 | Author: Nova-PM

## Problem Statement

Phoenix Trade Bot currently has two separate pipeline trading codebases:

1. **Current repo (ProjectPhoneix)**: An in-flight pipeline-worker service (uncommitted) that provides a deterministic, non-AI trading engine as an alternative to the Claude SDK engine. Core pipeline logic, DB schema (migration 045), and service scaffolding exist, but lack proven non-AI pipeline logic and broker flexibility.
2. **OldProject/**: A legacy Kafka-based pipeline trader with ~860 files — production-proven regex signal parsing, trade validation, execution logic, position monitoring. Uses **Alpaca** and is designed for a single-broker world.

Additionally, Phoenix's current broker integration is limited to Robinhood via MCP tools. Enterprise users need multi-broker support starting with Interactive Brokers (IBKR).

## Goals

1. Consolidate pipeline logic from OldProject into `services/pipeline-worker/` without porting Kafka or Alpaca.
2. Multi-broker foundation: Robinhood (extend existing MCP integration) and Interactive Brokers (new adapter).
3. Complete pipeline dashboard UI (uncommitted Agents.tsx, Connectors.tsx, AgentDashboard.tsx edits).
4. Delete `OldProject/` after QA sign-off.

## Non-Goals

- AI-driven pipeline agents (Phase B)
- Backtesting enhancements (Phase C)
- OpenClaw integration (Phase F)
- Live trading rollout (paper mode only for Phase A)
- Kafka migration (use existing Redis Streams)
- OldProject's dashboard/auth (reference-only)
- Alpaca support (extract logic patterns, not broker binding)

## User Stories

### US-1: Pipeline Agent Creation
As a trader who wants deterministic (non-AI) execution, I want to create a "pipeline" agent instead of an "SDK" agent so that I can trade signals without LLM costs or latency.

**Acceptance:** Agent creation wizard has Engine Type selector (SDK/Pipeline); pipeline agents skip Claude SDK spawn; pipeline agents display engine badge.

### US-2: Broker Selection per Pipeline
As a trader with accounts at both Robinhood and IBKR, I want to assign a broker per pipeline agent so that I can route different signal sources to different brokers.

**Acceptance:** Broker dropdown in wizard (Robinhood default, IBKR option); stored in `agent.config.broker_type`; worker routes orders via correct adapter; paper-mode works for both.

### US-3: Regex Signal Parsing (OldProject Port)
As a pipeline agent, I want to parse Discord messages like "Bought SPX 6940C at 4.80" using regex (no LLM) so that I can execute immediately without AI overhead.

**Acceptance:** `pipeline/signal_parser.py` uses OldProject's `trade_parser.py` regex; extracts action, ticker, strike, option_type, price, quantity, expiration; no LLM fallback; 10+ real-message unit tests.

### US-4: Trade Validation (OldProject Port)
As a pipeline agent, I want to validate trades before execution using position limits, blacklists, and buying power checks.

**Acceptance:** `pipeline/risk_checker.py` implements OldProject's `TradeValidator` logic; returns `(is_valid, error_message)`; rejections logged to `agent_logs` and published to `stream:agent-messages`.

### US-5: End-to-End Pipeline Execution (Robinhood Paper)
As a QA engineer, I want to verify a full pipeline flow: Discord → parse → validate → Robinhood paper order.

**Acceptance:** Post "Bought AAPL 200C at 5.00 Exp: 05/16/2026" to test channel; pipeline agent (Robinhood, paper) processes within 2s; order visible in dashboard Trades; `pipeline_worker_state` shows `signals_processed=1`, `trades_executed=1`.

### US-6: End-to-End Pipeline Execution (IBKR Paper)
Same as US-5 but broker=IBKR; order appears in IBKR paper account; agent logs show broker_type=ibkr, order_id from IBKR.

### US-7: Pipeline Dashboard Stats
Detail page shows Pipeline Stats panel when engine_type=pipeline: signals_processed, trades_executed, signals_skipped, last_heartbeat, uptime. Refreshes every 5s.

## Functional Requirements

### F-1: Pipeline Logic Port (OldProject → pipeline-worker)

| OldProject File | Target Location | What to Port |
|---|---|---|
| `parsing/trade_parser.py` | `pipeline/signal_parser.py` | Regex patterns for BUY/SELL, ticker/strike/type, expiration parsing |
| `trading/trade_validator.py` | `pipeline/risk_checker.py` | Validation: blacklist, position limits, buying power, percentage-sell |
| `services/execution_service.py` | `agent_worker.py` (execution step) | Percentage-sell qty calc, dry-run, order placement sequence |
| `trading/position_manager.py` | `pipeline/position_tracker.py` (new) | Position state — use DB, not in-memory |

**Critical exclusions:** Kafka transport; Alpaca client; OldProject DB models; OldProject auth/dashboard.

### F-2: Broker Adapter — Robinhood (Pipeline Mode)

Create `shared/broker/robinhood_adapter.py` implementing `BrokerAdapter` protocol, wrapping the existing Robinhood MCP client as an async Python adapter. Methods: `place_limit_order`, `place_bracket_order`, `cancel_order`, `get_order_status`, `get_positions`, `get_account`, `format_option_symbol`. Register in `shared/broker/factory.py` as `"robinhood": RobinhoodBrokerAdapter`.

### F-3: Broker Adapter — Interactive Brokers (New)

Create `shared/broker/ibkr_adapter.py` implementing `BrokerAdapter` protocol, connecting to IBKR paper/live account. Methods: same as Robinhood. Register as `"ibkr": IBKRBrokerAdapter`.

**API Path Options (Atlas to decide):**
1. **TWS API (ib_insync)**: Mature, fast, full coverage, but requires TWS/IB Gateway running locally.
2. **Client Portal Gateway (REST)**: Docker-deployable, REST/JSON, but newer and less mature.

**Acceptance:** Paper orders succeed; IBKR-specific OCC symbol formatting handled; circuit breaker on connection loss with exponential backoff.

### F-4: Pipeline Worker Enhancements

- Broker selection: read `agent.config.broker_type`, instantiate via `shared.broker.factory.create_broker_adapter`.
- Percentage-sell qty calc: if `quantity="50%"`, query DB for current position, compute absolute qty.
- Position tracking: update `agent_positions` (or add `current_position_qty` to `AgentTrade`).
- Dry-run mode: respect `config.dry_run_mode`.
- Kill-switch: subscribe to `stream:kill-switch`, stop all workers within 2s.

### F-5: Dashboard UI Completion

Uncommitted files to finish: `apps/dashboard/src/pages/{Agents,Connectors,AgentDashboard}.tsx`, `apps/dashboard/src/types/agent.ts`.

- Engine Type radio in creation wizard (SDK/Pipeline)
- Broker dropdown when Pipeline selected (Robinhood/IBKR)
- Engine + broker badges on agent cards
- Pipeline Stats panel on detail page (polling every 5s via TanStack Query)

### F-6: API Changes

- `POST /api/v2/agents` — add `broker_type` (required when engine_type=pipeline).
- `GET /api/v2/agents/{id}` — include `runtime_info.pipeline_stats` from `pipeline_worker_state`.
- `POST /api/v2/agents/{id}/approve` — route to `pipeline-worker:8055/workers/start` when engine_type=pipeline instead of spawning Claude session.

## Acceptance Criteria

1. OldProject's regex parser ported with 10+ tests passing; validation ported with 8+ tests; no Kafka/Alpaca imports in `services/pipeline-worker/`.
2. Robinhood and IBKR adapters implement all protocol methods; factory registers both; mocked-API unit tests for both.
3. End-to-end Robinhood paper: Discord message → parse → validate → MCP order → trade in dashboard → no errors; `pipeline_worker_state` correct.
4. End-to-end IBKR paper: same, order appears in IBKR paper account.
5. Dashboard: engine selector works; broker dropdown conditional on Pipeline; badges render; pipeline stats panel only for pipeline agents; 5s refresh.
6. Regression: SDK agents unaffected — backtest, lifecycle, UI.
7. Cleanup: `OldProject/` deleted after QA sign-off.

## Dependencies

- `docs/architecture/pipeline-engine.md` (ADR-004, 742 lines)
- Uncommitted pipeline-worker scaffold (`services/pipeline-worker/`)
- `agents/templates/live-trader-v1/tools/robinhood_mcp_client.py` (existing Robinhood MCP tooling)
- Migration `045_pipeline_engine.py`
- `shared/broker/adapter.py` (protocol)

## Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R-1 | **IBKR API path choice unresolved** — TWS API vs Client Portal Gateway. Wrong choice = rework. | CRITICAL | Atlas must decide before F-3 implementation; evaluate deployment complexity, stability, coverage. |
| R-2 | Alpaca-specific assumptions leak in OldProject-ported logic | HIGH | Port logic *patterns*, not Alpaca code; cross-broker integration tests. |
| R-3 | Merge conflicts with uncommitted pipeline work | MEDIUM | Commit existing scaffold as "WIP: pipeline engine scaffold" before Phase A begins. |
| R-4 | Users assume Phase A enables live trading | MEDIUM | UI "Paper" badge; API rejects `trading_mode=live` for pipeline agents. |
| R-5 | Regex parser fragility for Phoenix channels | MEDIUM | Port OldProject's ~20 tests; add Phoenix-channel-specific cases; no LLM fallback in scope. |

## Open Questions for Atlas

1. **IBKR API choice**: TWS API (ib_insync) vs Client Portal Gateway (REST)?
2. **Broker config scope**: per-pipeline (agent.config.broker_type) vs per-user (TradingAccount default)?
3. **Symbol normalization**: OCC-normalized in adapters or keep broker-native? Impacts Trade schema/UI.
4. **Position tracking**: extend `AgentTrade` with `current_position_qty`, or new `AgentPosition` table?
5. **IBKR paper credentials**: nested JSON in `TradingAccount.credentials_encrypted`, or separate account rows?
6. **Robinhood MCP adapter mode**: sidecar per pipeline-worker, or shared singleton?

## Out of Scope (Future Phases)

- Phase A-Live (live trading rollout)
- Phase B (AI-enhanced pipelines)
- Phase C (unified backtest engine)
- Additional brokers (Tradier, TD, Schwab)
- Hybrid agents (pipeline entry, LLM exit)
- Phase F (OpenClaw removal)
- Dashboard charting (equity curve, trade distribution)

## Testing Strategy

- Unit: `tests/unit/pipeline_worker/test_signal_parser.py` (20+ regex cases); `test_risk_checker.py` (15+ scenarios); mocked-API adapter tests.
- Integration: `tests/integration/test_pipeline_flow.py`; `test_broker_adapters.py` with real paper accounts.
- E2E (YAML regression): pipeline agent creation journey; pipeline execution Robinhood; pipeline execution IBKR; SDK agent unchanged.

## Success Metrics

1. OldProject deleted; 0 Kafka imports; 0 Alpaca imports outside broker adapter.
2. 2 brokers supported, both paper-verified.
3. Signal-to-decision < 500ms p95 (vs 3–8s for SDK agents).
4. Pipeline worker test coverage > 80%.

## Rollout Plan (High-Level Phasing within A)

- **A.1** Foundation: commit scaffold, apply migration, port parser + risk checker, unit tests.
- **A.2** Robinhood adapter: wrap MCP, register, unit + integration tests.
- **A.3** IBKR adapter: after Atlas's API-path decision; implement, register, test.
- **A.4** Pipeline worker completion: broker selection, pct-sell, position tracking, dry-run, kill-switch.
- **A.5** Dashboard UI: wizard, badges, stats panel.
- **A.6** API integration: agent routes updated, approve routing.
- **A.7** E2E + QA sign-off.
- **A.8** Cleanup: delete OldProject/, commit.

## Handoff to Atlas-Architect

Atlas produces: IBKR API decision + justification; Robinhood MCP adapter architecture; broker symbol normalization strategy; position tracking schema; paper/live credential management; OpenAPI updates; DB schema confirmation; component + sequence diagrams (agent creation with broker, signal processing, percentage-sell flow).
