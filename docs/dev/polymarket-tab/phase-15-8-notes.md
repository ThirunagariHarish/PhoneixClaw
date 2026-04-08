# Phase 15.8 Implementation Notes

**Phase:** 15.8 — Integration Wire-Up  
**Date:** 2025-04-08  
**Author:** Devin (dev)  
**Status:** Complete — pending Cortex review

---

## Summary

Phase 15.8 wires all previously-built Phase 15 components into the existing platform
infrastructure.  The main changes are:

1. `TopBetsAgent` registered in the orchestrator service (starts automatically when enabled).
2. Schema safety-net entries added for critical `pm_top_bets` / `pm_chat_messages` columns.
3. Docker service `pm-top-bets-agent` added under the `agents` profile.
4. New env vars documented in `.env.example`.
5. `PredictionMarketsConfig` dataclass added to `shared/config/base_config.py`.
6. Centralised `TopBetsConfig` dataclass created (`agents/polymarket/top_bets/config.py`).
7. Integration smoke tests added in `tests/integration/test_pm_integration.py`.
8. `SETUP.md` updated with a "Prediction Markets Agent" section (§11).

No breaking changes were made to any existing service.

---

## Files Changed

### Created

| File | Purpose |
|------|---------|
| `agents/polymarket/top_bets/config.py` | Centralised env-based config loader for `TopBetsConfig` |
| `tests/integration/test_pm_integration.py` | Integration smoke tests (3 tests) |
| `docs/dev/polymarket-tab/phase-15-8-notes.md` | This file |

### Modified

| File | Change |
|------|--------|
| `services/orchestrator/src/main.py` | Added `TopBetsAgent` registration in `lifespan()` |
| `apps/api/src/main.py` | Added 7 safety-net `ALTER TABLE` / column stmts in `_ensure_prod_schema()` |
| `docker-compose.yml` | Added `pm-top-bets-agent` service under `profiles: [agents]` |
| `docker-compose.dev.yml` | Added dev env-override for `pm-top-bets-agent` |
| `.env.example` | Added `PM_TOP_BETS_ENABLED`, `PM_TOP_BETS_VENUE`, `PM_TOP_BETS_CYCLE_INTERVAL_S`, `PM_RESEARCH_ENABLED` |
| `shared/config/base_config.py` | Added `PredictionMarketsConfig` dataclass + `AppConfig.prediction_markets` field |
| `SETUP.md` | Added §11 "Prediction Markets Agent" section |

---

## Detailed Changes

### 1. Orchestrator registration (`services/orchestrator/src/main.py`)

The `lifespan()` async context manager now:
- Reads `PM_TOP_BETS_ENABLED` (default `"true"`) and `PM_TOP_BETS_VENUE` (default `"robinhood_predictions"`).
- When enabled, constructs a `TopBetsAgent` (with its own `session_factory` from `DATABASE_URL`),
  wraps it in a `PMAgentRuntime`, registers the runtime with `register_pm_runtime` (so the existing
  kill-switch fan-out handler can trip/rearm it), and starts it as a background `asyncio.Task`.
- On shutdown, calls `runtime.stop()` and cancels the background task cleanly.
- The entire block is wrapped in a broad `except Exception` so an agent startup failure never
  prevents the orchestrator from serving its stream-polling function.

### 2. Schema safety net (`apps/api/src/main.py`)

Added 7 idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` statements to the `_ensure_prod_schema()`
function's `statements` list:

```sql
ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS bull_argument TEXT;
ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS bear_argument TEXT;
ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS sample_probabilities JSONB;
ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS reference_class VARCHAR(100);
ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS base_rate_yes FLOAT;
ALTER TABLE pm_top_bets ADD COLUMN IF NOT EXISTS confidence_score FLOAT;
ALTER TABLE pm_chat_messages ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT false;
```

Each statement runs in its own short transaction (existing pattern), so a table-not-found error
on a fresh DB (where the `pm_*` tables haven't been created yet) is logged as a warning, not a crash.

### 3. Docker service (`docker-compose.yml` + `docker-compose.dev.yml`)

`pm-top-bets-agent` service:
- `build: .` (same Dockerfile as the rest of the platform).
- `command: python -m agents.polymarket.top_bets.runner` (uses the existing standalone runner).
- `profiles: [agents]` — **not** started by `docker compose up` by default.
- `depends_on: [postgres, redis]`.
- All new env vars (`PM_TOP_BETS_VENUE`, `PM_TOP_BETS_ENABLED`, `PM_TOP_BETS_CYCLE_INTERVAL_S`)
  are passed through with safe defaults.
- `docker-compose.dev.yml` adds a per-service env override block for local development.

### 4. `agents/polymarket/top_bets/config.py`

New `TopBetsConfig` dataclass with a `from_env()` classmethod.  Reads:
- `PM_TOP_BETS_VENUE` (default: `"robinhood_predictions"`)
- `PM_TOP_BETS_CYCLE_INTERVAL_S` (default: `60`)
- `PM_TOP_BETS_ENABLED` (default: `"true"`)

Additional fields (`debate_top_k`, `cot_samples`) default to the same values as `config.yaml` for
programmatic construction in tests / non-runner contexts.

### 5. `shared/config/base_config.py`

New `PredictionMarketsConfig` dataclass with four fields:
- `pm_top_bets_enabled`, `pm_top_bets_venue`, `pm_top_bets_cycle_interval_s`, `pm_research_enabled`

All use `field(default_factory=lambda: …)` to defer `os.getenv` evaluation, matching the pattern
used by `RiskConfig` and `ExecutionConfig`.  The field is added to `AppConfig` as
`prediction_markets: PredictionMarketsConfig`.

### 6. Integration smoke tests (`tests/integration/test_pm_integration.py`)

Three tests, all using mocks only (no real infrastructure required):

| Test | What it exercises |
|------|-------------------|
| `test_ingest_then_embed_then_score` | `HistoricalIngestPipeline.run()` → `EmbeddingStore.embed_unprocessed()` → `TopBetScorer.score_batch()`. Asserts confidence ∈ [0, 1]. |
| `test_agent_cycle_end_to_end` | One `TopBetsAgent.run_cycle()` with patched `_fetch_markets`, `_score_and_filter`, `_persist_top_bets`, `_publish_to_stream`. Asserts `CycleResult.error is None` and `top_bets_persisted >= 1`. |
| `test_api_top_bets_endpoint_returns_data` | FastAPI `TestClient`. DB dependency overridden with `_FakeSession` seeded with one `PMTopBet`. Asserts `GET /api/v2/pm/top-bets` → HTTP 200. |

Note: `make test` runs `tests/unit/` and `apps/api/tests/` only.  The integration tests live in
`tests/integration/` and must be run explicitly:
```bash
PYTHONPATH=. pytest tests/integration/test_pm_integration.py -v
```

---

## Deviations from Architecture Doc

None. All changes match §8 Phase 15.8 and §13 Integration in
`docs/architecture/polymarket-phase15.md`.

---

## Open Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `pm_top_bets` table may not exist on a fresh DB before `init_db.py` runs | Low | Safety-net stmts log a warning and continue; table is created by `init_db.py` before the agent needs it |
| Orchestrator startup failure if `agents` package is not importable | Low | `except Exception` guard logs the error and falls back to running without the agent |
| `docker-compose.dev.yml` partial-override pattern requires `docker compose` ≥ v2 | Low | All team environments and CI use Compose v2 |
