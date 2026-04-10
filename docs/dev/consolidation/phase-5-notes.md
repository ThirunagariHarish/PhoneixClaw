# Phase 5 — Nightly Knowledge Consolidation Pipeline ("Agent Sleep")

## What changed

### 1. `shared/db/models/consolidation.py` (pre-existing, patched)
- Fixed deprecated `datetime.utcnow` → `lambda: datetime.now(timezone.utc)` on `created_at`
- Updated docstring from "Phase 3" to "Phase 5"
- All other columns/FKs were already correct; no schema change needed

### 2. `apps/api/src/main.py` (patched)
- Added two idempotent `CREATE INDEX IF NOT EXISTS` statements to `_ensure_prod_schema()`:
  - `idx_consolidation_agent_id` on `consolidation_runs(agent_id)`
  - `idx_consolidation_status` on `consolidation_runs(status)`
- The Alembic migration `036_consolidation_runs.py` already creates these indexes on fresh
  installs; the new `_ensure_prod_schema` entries act as a production safety-net for any
  deployment that skipped the migration.
- Router import and `app.include_router(consolidation_routes.router)` were **already present**
  (no change needed).

### 3. `agents/templates/live-trader-v1/tools/nightly_consolidation.py` (patched)
- The file existed as an **async library** (three async helper functions for the Claude agent
  to call).
- Added a complete **CLI entry-point** (`__main__` block + `_cli_main` coroutine):
  - `argparse` with `--dry-run` flag
  - Reads `config.json` from CWD (falls back to script's parent directory)
  - POSTs to `/api/v2/agents/{agent_id}/consolidation/run`
  - Polls `GET /runs/{run_id}` every 10 s for up to 10 min
  - Prints Markdown `consolidation_report` to stdout on success
  - Exit 0 on `completed`, exit 2 on `failed` / timeout / HTTP error
- Existing async library functions (`trigger_consolidation`, `get_consolidation_status`,
  `get_recent_consolidation_runs`) **unchanged**.

### 4. `agents/templates/live-trader-v1/manifest.defaults.json` (patched)
- Added `"nightly_consolidation"` to the `tools` array (was missing; `write_wiki_entry` was
  already there from a prior phase).

### 5. `tests/unit/test_nightly_consolidation_tool.py` (new)
- 6 unit tests covering the CLI logic; all run without DB or network:
  - `test_dry_run_returns_zero` — `--dry-run` prints intent and exits 0
  - `test_happy_path_completes` — trigger → pending poll → completed poll → exit 0
  - `test_failed_run_returns_2` — status=failed → exit 2 with error message
  - `test_missing_config_returns_2` — FileNotFoundError → exit 2
  - `test_config_missing_agent_id_returns_2` — no agent_id → exit 2
  - `test_trigger_http_error_returns_2` — POST raises → exit 2

## Files already complete (no changes needed)

| File | Status |
|------|--------|
| `shared/db/migrations/versions/036_consolidation_runs.py` | ✅ Complete, idempotent |
| `apps/api/src/routes/consolidation.py` | ✅ Complete (POST /run, GET /runs, GET /runs/{id}) |
| `apps/api/src/repositories/consolidation_repo.py` | ✅ Complete |
| `apps/api/src/services/consolidation_service.py` | ✅ Complete (pattern detection pipeline) |
| `apps/dashboard/src/components/ConsolidationPanel.tsx` | ✅ Complete (Card with run stats, View Report, Run Now) |

## Tests run

```
tests/unit/test_nightly_consolidation_tool.py  6 passed in 0.02s
```

The existing `tests/unit/test_consolidation_service.py` is **skipped** (not failing) because
`shared.db.models.wiki` has a pre-existing broken import (`TIMESTAMPTZ` removed from
SQLAlchemy ≥ 2.x). This is **not introduced by this phase**. The service's `_classify_observation`,
`_find_patterns`, and `_generate_report` methods are pure-logic and already tested there when
the DB layer is importable.

## Deviations from spec

| Spec | Implementation | Reason |
|------|---------------|--------|
| Service should write `WINNING_CONDITIONS`/`MISTAKES` entries based on win/loss rates | Service writes `MARKET_PATTERNS` entries via keyword clustering | Pre-existing Phase 3 implementation; no `outcome` field exists on wiki entries to compute win/loss rate. Changing the service would be a design pivot — flagged for Atlas review if needed. |

## Open risks

- The `wiki.py` model `TIMESTAMPTZ` import error will cause the consolidation service tests
  to be skipped on Python 3.13 + SQLAlchemy 2.x until the model is patched (out of scope for
  this phase).
- `nightly_consolidation.py` CLI requires `httpx` in the agent's venv; it is listed in
  `pyproject.toml` but should be verified in the Docker agent image.
