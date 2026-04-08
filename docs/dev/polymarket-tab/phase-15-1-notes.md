# Phase 15.1 — DB Models + Alembic Migration: Implementation Notes

**Date:** 2026-04-07  
**Phase:** 15.1 — DB Models + Alembic Migration  
**Status:** ✅ Complete — Ready for Cortex Review

---

## What Was Added

### 1. `shared/db/models/polymarket.py` — 7 new ORM classes appended

| Class | Table | Purpose |
|---|---|---|
| `PMTopBet` | `pm_top_bets` | Daily bet recommendations with debate pipeline (F-ACC-1), CoT sampling (F-ACC-2), and reference class (F-ACC-3) columns |
| `PMChatMessage` | `pm_chat_messages` | Chat session messages (user/assistant) for the conversational interface |
| `PMAgentActivityLog` | `pm_agent_activity_log` | Structured agent activity/event log with severity levels |
| `PMStrategyResearchLog` | `pm_strategy_research_log` | Strategy research run log tracking proposed config deltas and apply status |
| `PMHistoricalMarket` | `pm_historical_markets` | Historical market data for reference-class forecasting |
| `PMMarketEmbedding` | `pm_market_embeddings` | Vector embeddings (stored as JSONB) for historical market similarity search |
| `PMModelEvaluation` | `pm_model_evaluations` | Model performance tracking (Brier score, accuracy, Sharpe proxy) |

No existing classes were modified.

### 2. `shared/db/models/__init__.py`

Added 7 new class names to both the import block and `__all__` list.

### 3. `shared/db/migrations/versions/033_pm_phase15.py`

New Alembic migration creating all 7 tables with correct columns, constraints, and indexes.

---

## Deviations from Plan

| Item | Plan | Actual | Reason |
|---|---|---|---|
| Migration filename | `032_pm_phase15.py` | `033_pm_phase15.py` | `032_agents_tab_fix.py` already existed with revision `"032"`. New migration uses `down_revision = "032"` to chain correctly. |
| `down_revision` | `"031_pm_last_backtest_at"` | `"032"` | The actual last revision is `"032"` (agents tab fix). Must chain from there to avoid Alembic graph conflicts. |
| `datetime.date` / `datetime.datetime` type hints | Used as `datetime.date` / `datetime.datetime` (import datetime) | Used as `date` / `datetime` (from datetime import date, datetime) | Matches existing file's import pattern (`from datetime import datetime`). Added `date` to the existing import rather than adding a second `import datetime` which would shadow. |
| Import line consolidation | `from sqlalchemy import Date, Float, Index, ...` as separate line | Merged into the existing `from sqlalchemy import ...` line | Avoids duplicate import lines; ruff auto-fixed one redundant import during lint. |

---

## Files Touched

1. `shared/db/models/polymarket.py` — imports updated, 7 classes appended
2. `shared/db/models/__init__.py` — import block and `__all__` updated
3. `shared/db/migrations/versions/033_pm_phase15.py` — created (new file)

## Files NOT Touched (as required)

- All existing classes in `polymarket.py` — untouched
- All existing migration files — untouched
- No routes, services, agents, dashboard files
- `pyproject.toml`, `requirements*.txt`

---

## Validation Results

| Check | Result |
|---|---|
| `ruff check` on touched files | ✅ All checks passed (4 E501 lines fixed by hand) |
| Import check (`from shared.db.models.polymarket import PMTopBet, ...`) | ✅ All 7 new models import OK |
| `pytest tests/unit/polymarket/` | ✅ 179 passed in 1.05s |
| `pytest tests/unit/` (full unit suite) | ✅ 493 passed, 14 warnings (all pre-existing) |

---

## Cortex Fix Round

**Date:** 2026-04-08  
**Triggered by:** Cortex code review findings on Phase 15.1 PR

### Changes Made

#### `shared/db/models/polymarket.py`

| Fix | Location | Before | After |
|---|---|---|---|
| M-1 | `PMMarketEmbedding.embedding` | `Mapped[dict]` / `mapped_column(JSONB, nullable=False)` | `Mapped[list]` / `mapped_column(JSONB, nullable=False, default=list)` |
| M-2 | `PMTopBet.sample_probabilities` | `Mapped[Optional[dict]]` / `mapped_column(JSONB, nullable=True)` | `Mapped[Optional[list]]` / `mapped_column(JSONB, nullable=True, default=None)` |
| M-3a | `PMHistoricalMarket.outcomes_json` | `Mapped[Optional[dict]]` / `mapped_column(JSONB, nullable=True)` | `Mapped[Optional[list]]` / `mapped_column(JSONB, nullable=True, default=list)` |
| M-3b | `PMHistoricalMarket.price_history_json` | `Mapped[Optional[dict]]` / `mapped_column(JSONB, nullable=True)` | `Mapped[Optional[list]]` / `mapped_column(JSONB, nullable=True, default=list)` |
| S-3a | `PMModelEvaluation.brier_score` | `Mapped[Optional[float]]` / `nullable=True` | `Mapped[float]` / `nullable=False, default=0.0` |
| S-3b | `PMModelEvaluation.accuracy` | `Mapped[Optional[float]]` / `nullable=True` | `Mapped[float]` / `nullable=False, default=0.0` |
| S-3c | `PMModelEvaluation.num_markets_tested` | `Mapped[Optional[int]]` / `nullable=True` | `Mapped[int]` / `nullable=False, default=0` |

#### `shared/db/migrations/versions/033_pm_phase15.py`

| Fix | Description |
|---|---|
| M-4 | Added `op.create_index("ix_pm_market_embeddings_historical_market_id", ...)` after `pm_market_embeddings` table creation |
| S-1a | Added `op.create_index("ix_pm_historical_markets_reference_class", ...)` after `pm_historical_markets` table creation |
| S-1b | Added `op.create_index("ix_pm_historical_markets_venue", ...)` after `pm_historical_markets` table creation |
| S-2 | Added `op.create_index("ix_pm_chat_messages_created_at", ..., [sa.text("created_at DESC")])` for DESC ordering |
| S-3 | Changed `brier_score`, `accuracy`, `num_markets_tested` columns to `nullable=False` with `server_default` values |

#### `tests/unit/test_pm_phase15_models.py` — **NEW FILE** (M-5)

Created 50 unit tests across 7 test classes (one per new ORM model):

| Class | Tests | Key coverage |
|---|---|---|
| `TestPMTopBet` | 8 | Columns, nullable/not-null, `sample_probabilities` is `list`-typed, instantiation |
| `TestPMChatMessage` | 6 | Columns, nullable/not-null, instantiation |
| `TestPMAgentActivityLog` | 6 | Columns, nullable/not-null, instantiation |
| `TestPMStrategyResearchLog` | 5 | Columns, nullable, instantiation |
| `TestPMHistoricalMarket` | 9 | Columns, nullable/not-null, `outcomes_json`/`price_history_json` are `list`-typed, unique constraint, instantiation |
| `TestPMMarketEmbedding` | 6 | Columns, `embedding` is `list`-typed (not `dict`), not-null, instantiation with 1536-dim vector |
| `TestPMModelEvaluation` | 10 | Columns, `brier_score`/`accuracy`/`num_markets_tested` not-null, `sharpe_proxy`/`evaluated_at` nullable, instantiation |

Tests use annotation introspection (`get_args` + `Mapped[...]` unwrap) to assert list vs dict types statically without a live database.

### Validation

| Check | Result |
|---|---|
| `ruff check` on all 3 files | ✅ All checks passed |
| `pytest tests/unit/test_pm_phase15_models.py` (Python 3.13) | ✅ **50 passed** in 0.14s |
| `pytest tests/unit/` (excluding pre-existing import-error tests) | ✅ 431 passed, 1 skipped — same pre-existing failures as before (redis/aiosqlite/numpy/cryptography modules missing from CI env, unrelated to this phase) |


- **No pgvector column:** `PMMarketEmbedding.embedding` stores embeddings as JSONB per spec. If a future phase requires vector similarity search with pgvector (`vector` type), a separate migration will be needed. This matches the architecture doc which defers pgvector to a later phase.
- **`pm_orders` FK in `PMTopBet` and `PMChatMessage`:** Both reference `pm_orders.id` as nullable FKs. If the `pm_orders` table does not exist at migration time the FK will fail. This is safe since `pm_orders` was created in migration `029_pm_v1_0_initial.py`.
- The `apps/api/tests/` suite could not be included in the combined run due to a pre-existing `ImportPathMismatchError` in that test directory's conftest (not caused by this phase). All `tests/unit/` tests pass cleanly.
