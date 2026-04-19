# PRD: Phase D — Pipeline Dashboard Completion

Version: 1.0 | Status: Draft | Date: 2026-04-18 | Author: Nova-PM

## Problem Statement

Phase A introduced `services/pipeline-worker/` and `engine_type` on agents. The dashboard UX is incomplete — traders cannot create pipeline agents, distinguish them at a glance, or monitor pipeline-specific stats. The repo has uncommitted dashboard edits (`Agents.tsx`, `Connectors.tsx`, `AgentDashboard.tsx`, `types/agent.ts`, `Agents.canAdvance.test.tsx`) that must be finished, tested, and integrated with Phase A's backend changes.

## Goals

1. Enable pipeline agent creation via wizard with conditional broker selection.
2. Visual distinction (engine + broker badges) on the agents list.
3. Pipeline Stats panel on the agent detail page with 5s polling.
4. Broker account integration aligned with Phase A's scope decision.
5. Graceful empty/error states ("Waiting for first signal", "Pipeline worker offline").
6. Test coverage for wizard pipeline path (canAdvance, AgentCard, AgentDashboard).

## Non-Goals

- AI agent dashboard changes
- Backtest UI for pipeline agents
- OpenClaw Bridge UI
- WebSocket streaming (polling is sufficient for v1)
- Pipeline worker config editor
- Multi-broker pipeline agents
- Historical stats charting
- SDK vs pipeline performance comparison

## User Stories

### US1: Trader creates a pipeline agent
Wizard step 0 shows engine cards (SDK / Pipeline). Step 1 conditionally shows Broker dropdown when engine=Pipeline. Submit includes `engine_type: "pipeline"` and `config.broker_account_id` (if per-agent scope).

**Acceptance:** wizard blocks advance if broker missing and per-agent scope; backend creates `engine_type=pipeline`; SDK-specific steps hidden when pipeline.

### US2: Trader distinguishes pipeline from SDK agents
Agents list card shows engine badge (blue SDK, green Pipeline) + broker badge (Robinhood/IBKR) for pipeline agents. Doesn't overlap RUNNING/PAUSED/ERROR status badges.

### US3: Trader monitors pipeline stats
Agent detail page conditionally renders Pipeline Stats panel when `engine_type=pipeline`. Shows signals_processed, trades_executed, signals_skipped, last_heartbeat (relative time), uptime. Polls every 5s via TanStack Query `refetchInterval: 5000, staleTime: 0`. Worker-status-aware: STOPPED → "(Offline)"; ERROR → banner.

### US4: Helpful empty/error states
- `signals_processed===0 && worker_status===RUNNING` → "Waiting for first signal…"
- `worker_status===STOPPED` → "Pipeline worker is stopped. Click Resume to restart."
- `worker_status===ERROR` → "Pipeline worker encountered an error: {error_message}. Check logs or restart."
- Stale heartbeat (>5 min) while RUNNING → "Heartbeat stale — may be offline"

### US5: Pause / Resume
Pause/Resume buttons call existing `POST /api/v2/agents/{id}/pause|resume`; backend routes to pipeline-worker `/workers/{id}/stop|start`. UI updates immediately; stats polling pauses/resumes.

## Functional Requirements

### FR1: Agent Creation Wizard
**Step 0:** Engine Type cards with icon + title + description + Select; sets `form.engine_type`.

**Step 1:** When `engine_type==="pipeline"` (and per-agent scope): required Broker Account dropdown fetching `GET /api/v2/trading-accounts?category=broker` (Alpaca, IBKR, Tradier, Robinhood). Store in `form.config.broker_account_id`.

**Validation:** `computeCanAdvance(1)` returns false if pipeline + missing broker_account_id (per-agent scope). Submit payload includes `engine_type` + `config.broker_account_id`.

### FR2: Agents List Badges
Top-right badge: SDK (blue) or Pipeline (green). Secondary broker badge below when pipeline + broker_account_id present. Uses Radix Badge + Tailwind.

### FR3: Pipeline Stats Panel
Renders when `agent.engine_type==="pipeline"`. Below PnL stats, above backtest history. Shows 5 metrics + circuit state. `useQuery({ queryKey: ['agent', id], refetchInterval: 5000, staleTime: 0 })`.

Empty/error handling per US4. Uses `formatDistanceToNow` for heartbeat; `formatDuration` for uptime.

### FR4: Connectors Page — Broker Category Audit
Reconcile with Atlas's Phase A scope decision:
- per-agent: broker dropdown in wizard; no change to Connectors.tsx.
- per-connector: broker selection in Connectors.tsx; remove from wizard.
- per-user: remove dropdown; rely on user default trading account.

Must match backend contract.

### FR5: Unit Tests
**`Agents.canAdvance.test.tsx`:**
- `canAdvance_step1_pipeline_no_broker` → false (per-agent scope)
- `canAdvance_step1_pipeline_with_broker` → true
- `canAdvance_step1_sdk_no_broker` → true

**`AgentCard.test.tsx`:**
- pipeline badge renders when `engine_type=pipeline`
- SDK badge renders when `engine_type=sdk`
- broker badge renders when pipeline + `config.broker_account_id`

**`AgentDashboard.test.tsx`:**
- pipeline stats panel shown when pipeline
- hidden when SDK
- empty state when `signals_processed=0 && worker_status=RUNNING`
- offline state when `worker_status=STOPPED`

## Acceptance Criteria

AC1. Wizard step 0 shows two engine cards with distinct icons.
AC2. Selecting Pipeline advances to step 1; step 1 conditionally renders Broker dropdown; validation blocks submit when broker missing.
AC3. `POST /api/v2/agents` payload includes `engine_type: "pipeline"` and `config.broker_account_id`.
AC4. Agents list renders engine badge per card; pipeline cards render broker badge.
AC5. Badges don't overlap status badges; contrast ratio >4.5:1.
AC6. Pipeline Stats panel only for pipeline agents; polls every 5s.
AC7. Empty/error/stale states display human-friendly messages.
AC8. Pause/Resume routes to pipeline-worker endpoints.
AC9. No "undefined"/"null" crashes; errors don't hide agent name/PnL/actions.
AC10. All new tests pass in `make test-dashboard`.

## Dependencies

1. **Phase A backend**: `engine_type` column, `broker_type` in POST body, `runtime_info.pipeline_stats` in GET response, `pipeline_worker_state` populated.
2. **Atlas's broker-scope decision** — per-agent is the Phase A architecture decision; wizard must match.
3. **`GET /api/v2/trading-accounts`** — must return broker category entries.
4. **pipeline-worker running** at `PIPELINE_WORKER_URL` (default `http://localhost:8055`).

## Risks

1. **Uncommitted work conflicts** — commit existing edits to `feat/phase-d-dashboard` before pulling A changes.
2. **API contract drift** — define TypeScript `PipelineStats` interface; validate against API response in a contract test.
3. **TanStack Query cache collisions** — single query key `['agent', id]`; set `refetchInterval` only on detail page.
4. **Broker scope inconsistency** — block Phase D start until Atlas confirms; record in ADR.
5. **Heartbeat staleness false positives from clock skew** — use server timestamps (ISO 8601 TZ); test multi-TZ.

## Out of Scope

AI agent dashboard changes; backtest visualization; OpenClaw UI; WebSocket streaming; pipeline config editor; multi-broker per agent; time-series charts; SDK vs pipeline comparison.

## Open Questions for Atlas

1. **Broker scope**: per-agent (current A decision), per-connector, or per-user? Already chose per-agent — confirm dashboard matches.
2. **Stats field naming**: top-level (`agent.signals_processed`) vs nested (`agent.runtime_info.pipeline_stats.signals_processed`)? Atlas A doc says nested — align.
3. **WebSocket vs polling** for v1? Polling confirmed (5s).
4. **Stat card layout**: separate panel vs integrated into existing `MetricCard` grid? Confirm.
5. **Broker badge**: text (e.g., "Robinhood") vs icon? Suggest text + Lucide icon.

## Related Files

Uncommitted (WIP): `apps/dashboard/src/pages/{Agents,Connectors,AgentDashboard}.tsx`, `apps/dashboard/src/types/agent.ts`, `apps/dashboard/tests/unit/Agents.canAdvance.test.tsx`.

Backend (Phase A dependency): `apps/api/src/routes/agents.py`, `shared/db/models/agent.py`, `services/pipeline-worker/src/main.py`.

Architecture: `docs/architecture/phase-a-pipeline-consolidation.md`, `docs/architecture/pipeline-engine.md`.

## Success Metrics

- Pipeline agent creation success rate > 95%.
- Pipeline stats panel first-paint < 500ms.
- Polling ≤ 1 request / 5s / agent (no cache thrashing).
- New components: branch coverage > 80%.
- Zero regression in SDK agent creation/detail pages.
