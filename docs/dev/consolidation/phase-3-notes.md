# Phase 3 — Nightly Consolidation Pipeline ("Agent Sleep")

## Files Created

| File | Purpose |
|------|---------|
| `shared/db/models/consolidation.py` | `ConsolidationRun` SQLAlchemy model |
| `shared/db/migrations/versions/036_consolidation_runs.py` | Alembic migration (down_revision=035_agent_wiki) |
| `shared/config/market_holidays.py` | NYSE holiday calendar 2025–2026 + `is_trading_day()` |
| `apps/api/src/repositories/consolidation_repo.py` | `ConsolidationRepository` — CRUD + `list_agents_due_for_consolidation()` |
| `apps/api/src/services/consolidation_service.py` | `ConsolidationService` — 5-step pipeline |
| `apps/api/src/routes/consolidation.py` | 3 REST endpoints (POST 202, GET list, GET single) |
| `agents/templates/live-trader-v1/tools/nightly_consolidation.py` | Agent-facing httpx tool |
| `apps/dashboard/src/components/ConsolidationPanel.tsx` | React component with stats, report, and run list |
| `tests/unit/test_consolidation_service.py` | 25 unit tests |
| `apps/api/tests/test_consolidation_endpoints.py` | 12 endpoint/IDOR tests |
| `docs/dev/consolidation/phase-3-notes.md` | This file |

## Files Modified

| File | Change |
|------|--------|
| `shared/db/models/__init__.py` | Added `ConsolidationRun` import and `__all__` entry |
| `apps/api/src/services/scheduler.py` | Added `_job_consolidation_run()` + 18:15 ET cron job |
| `apps/api/src/main.py` | Registered `consolidation_routes.router`; added safety-net `CREATE TABLE IF NOT EXISTS consolidation_runs` in `_ensure_prod_schema()` |
| `apps/dashboard/src/pages/AgentDashboard.tsx` | Imported `ConsolidationPanel`; added it to the bottom of the Wiki tab |

## What Was Implemented

### ConsolidationRun Model
Tracks each run with: `run_type` (nightly/weekly/manual), `status` (pending/running/completed/failed), timestamps, counters for trades analyzed / wiki entries written-updated-pruned / patterns found / rules proposed, full Markdown report, and error message.

### Alembic Migration 036
Idempotent table creation with `_has_table()` guard, matching the pattern from 035_agent_wiki. Indexes on `agent_id` and `status`.

### ConsolidationService Pipeline (5 steps)
1. **Load** — fetch `TRADE_OBSERVATION` entries from last 30 days
2. **Find patterns** — group by `(symbol, pattern_type)`; ≥3 matching entries → pattern
3. **Write/update wiki** — create or update `MARKET_PATTERNS` entries for detected patterns
4. **Prune** — soft-delete `TRADE_OBSERVATION` entries older than 90 days with confidence < 0.30
5. **Propose rules** — for patterns with `avg_confidence ≥ 0.80` AND `count ≥ 5`, append to `agent.pending_improvements`

Pattern detection uses 6 keyword clusters: `bearish_reversal`, `bullish_breakout`, `support_hold`, `resistance_reject`, `volume_spike`, `gap_fill`.

### Scheduler Job
`_job_consolidation_run()` runs at 18:15 ET weekdays. Checks `is_trading_day(date.today())` first. Queries `manifest->>'consolidation_enabled' = 'true'` agents. Runs pipeline sequentially (memory-constrained).

### API Endpoints
```
POST /api/v2/agents/{agent_id}/consolidation/run      → 202 + creates pending run + fires asyncio.create_task
GET  /api/v2/agents/{agent_id}/consolidation/runs     → list (newest first, ?limit=10)
GET  /api/v2/agents/{agent_id}/consolidation/runs/{run_id}
```
All endpoints use `_get_agent_and_verify()` for IDOR protection (`request.state.user_id` / `is_admin`).

### Frontend
`ConsolidationPanel.tsx` — fetches recent runs, shows status chips (grey/blue-spinning/green/red), last run stats grid, collapsible Markdown report (`<pre>`), and recent runs list. "Run Now" button triggers POST → toast. Mounted at the bottom of the Wiki tab (AgentDashboard has 11 tabs ≥ 9).

## Test Results

```
tests/unit/test_consolidation_service.py   25 passed in 0.15s
apps/api/tests/test_consolidation_endpoints.py  12 passed in 0.21s
```

TypeScript check: `ConsolidationPanel.tsx` has zero errors. All pre-existing TS errors are in unrelated files.

## Deviations & Risks

- **react-markdown not installed**: dashboard `package.json` has no `react-markdown` dependency, so the report is rendered in a `<pre>` element instead. Raw Markdown is fully readable.
- **Sequential nightly job**: agents are processed one-by-one in the scheduler job (not parallel) to stay memory-safe, matching the ML pipeline pattern.
- **`asyncio_mode = auto`**: Tests do not need `@pytest.mark.asyncio` — matches project convention.
