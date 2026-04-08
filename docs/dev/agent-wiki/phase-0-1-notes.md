# Phase 0+1: Verifiable Alpha CI + Agent Knowledge Wiki — DB Layer

**Phase ID:** 0+1  
**Date:** 2025-01-15  
**Implementer:** Devin  

---

## What Changed

### Task 1 — Verifiable Alpha CI Gate (`apps/api/src/routes/agents.py`)

**`stage_pending_improvements` (PUT /{agent_id}/pending-improvements):**
- Initializes 3 new fields on each new improvement item before persisting:
  - `backtest_passed: None` — not run yet
  - `backtest_metrics: {}` — empty until validated
  - `validation_status: "pending_validation"` — initial state

**New endpoint `POST /{agent_id}/improvements/{improvement_id}/validate`:**
- Accepts `backtest_metrics` dict in body
- Applies thresholds: Sharpe ≥ 0.8, Win Rate ≥ 0.53, Max Drawdown ≥ -0.15, Profit Factor ≥ 1.3, Min Trades ≥ 15
- BORDERLINE logic: misses exactly ONE threshold by <10% (percent miss vs. absolute threshold)
- Sets `validation_status` → `approved | borderline | rejected`
- Patches the item in-place within `agent.pending_improvements` JSONB field and commits
- Returns `{improvement_id, validation_status, backtest_passed, backtest_metrics, thresholds_missed}`

### Task 2 — Wiki SQLAlchemy Model (`shared/db/models/wiki.py`)

- Added `WikiCategory` enum (8 values matching spec)
- Removed `VALID_WIKI_CATEGORIES` plain set (replaced by enum)
- Updated `trade_ref_ids` column: `ARRAY(UUID)` → `ARRAY(String)` (avoids SQLite test incompatibility and aligns with Alembic migration)
- Added `ondelete="SET NULL"` to `user_id` FK
- Added bidirectional ORM relationships:
  - `AgentWikiEntry.versions` → `list[AgentWikiEntryVersion]` (cascade all, delete-orphan)
  - `AgentWikiEntryVersion.entry` → `AgentWikiEntry`
- Timestamps use `datetime.now(timezone.utc)` defaults (tz-aware)

**Necessary side-effect fix — `apps/api/src/routes/wiki.py`:**
- `VALID_WIKI_CATEGORIES` set was moved to the model file in prior work then removed when the enum was introduced. Route still imported the set. Fixed by deriving it from `WikiCategory` in the route: `frozenset(c.value for c in WikiCategory)`. This keeps all route validators working unchanged.

### Task 3 — Alembic Migration (`shared/db/migrations/versions/035_agent_wiki.py`)

- Added 3 new idempotent index creates to `upgrade()`:
  - `idx_wiki_symbols` — GIN index on `symbols` array column
  - `idx_wiki_tags` — GIN index on `tags` array column  
  - `idx_wiki_shared_partial` — Partial index on `is_shared WHERE is_shared = true`
- `_has_index()` guard prevents duplicate index errors on re-run

### Task 4 — `_ensure_prod_schema()` (`apps/api/src/main.py`)

- Replaced simplified 2-column wiki table DDL with full schema (14 columns, FK constraints)
- Added 3 index safety-net entries: `idx_wiki_agent_id`, `idx_wiki_category`, `idx_wiki_versions_entry`
- GIN indexes excluded from safety-net (PostgreSQL-only syntax; safety-net already handles that via migration)

### Task 5 — Wiki Repository (`apps/api/src/repositories/wiki.py`) — NEW FILE

Implements `WikiRepository(BaseRepository)` with the full spec interface:

| Method | Description |
|--------|-------------|
| `list_entries(agent_id, category, tag, symbol, search, is_shared, active_only, page, per_page)` | Paginated list scoped to agent, all filters optional |
| `get_entry(entry_id, agent_id)` | IDOR-safe single entry fetch |
| `get_entry_versions(entry_id)` | Version history, oldest-first |
| `create_entry(agent_id, user_id, category, title, content, ...)` | Create + write v1 snapshot |
| `update_entry(entry_id, content, tags, is_active, is_shared, change_reason, updated_by)` | Bump version + snapshot |
| `soft_delete(entry_id)` | Sets `is_active=False` |
| `query_relevant(agent_id, query_text, category, top_k, include_shared)` | ILIKE on title/content/tags, ranked by confidence desc |
| `get_shared_entries(category, symbol, search, min_confidence, page, per_page)` | Cross-agent shared entries |
| `export_entries(agent_id, active_only)` | All entries, no pagination |
| `migrate_from_manifest(agent_id, user_id, knowledge_dict)` | Maps manifest keys to wiki categories |

**Note:** `apps/api/src/repositories/wiki_repo.py` (existing file) remains unchanged — it is used by the wiki routes. The new `wiki.py` is the canonical Phase 0+1 specification implementation.

### Task 6 — Unit Tests (`tests/unit/test_wiki_repository.py`) — NEW FILE

9 tests using SQLite in-memory via `aiosqlite`. Raw SQL table creation bypasses ARRAY/UUID type restrictions in SQLite. All tests use `SimpleNamespace` adapter to work with both SQLite rows and ORM objects.

| Test | Covers |
|------|--------|
| `test_create_entry` | Creates entry, verifies all fields |
| `test_list_entries_by_category` | Category filter isolation |
| `test_update_entry_increments_version` | Version bump + history row created |
| `test_soft_delete` | `is_active=False`, excluded from active list |
| `test_query_relevant_title_search` | ILIKE title search returns correct results |
| `test_get_shared_entries` | Only `is_shared=True` cross-agent entries |
| `test_wiki_repository_imports` | Import smoke test |
| `test_wiki_category_enum` | WikiCategory enum values |
| `test_version_history_ordering` | Versions returned oldest-first |

---

## Files Touched

| File | Action |
|------|--------|
| `apps/api/src/routes/agents.py` | Modified (2 changes: setdefault init + new endpoint) |
| `apps/api/src/routes/wiki.py` | Modified (necessary: VALID_WIKI_CATEGORIES now derived from enum) |
| `shared/db/models/wiki.py` | Modified (enum, relationships, FK fix, tz-aware timestamps) |
| `shared/db/models/__init__.py` | Modified (WikiCategory added to imports and __all__) |
| `shared/db/migrations/versions/035_agent_wiki.py` | Modified (3 GIN/partial indexes added) |
| `apps/api/src/main.py` | Modified (full wiki DDL replacing simplified version) |
| `apps/api/src/repositories/wiki.py` | Created (new, 10-method spec implementation) |
| `tests/unit/test_wiki_repository.py` | Created (9 tests, all passing) |

---

## Test Results

```
tests/unit/test_wiki_repository.py  — 9/9 passed
tests/unit/test_wiki_models.py      — 10/10 passed
tests/unit/test_write_wiki_entry.py — 25/25 passed
tests/unit/test_backtest_ci.py      — 27/27 passed
```

---

## Deviations from Spec

1. **`apps/api/src/routes/wiki.py` touched** — Not listed in file ownership but was a necessary fix. Removing `VALID_WIKI_CATEGORIES` from the model without updating the route would have broken all wiki API endpoints at runtime. Change is minimal (1 import swap + 1 constant derivation line).

2. **`wiki.py` vs `wiki_repo.py`** — The spec asked for `apps/api/src/repositories/wiki.py` as NEW. The existing `wiki_repo.py` is used by the wiki routes and was not changed. The new `wiki.py` provides the spec-compliant interface.

3. **GIN indexes excluded from `_ensure_prod_schema()`** — GIN syntax is PostgreSQL-only; the safety-net DDL runs against any engine. GIN indexes are handled by the Alembic migration which has proper conditional guards.

---

## Open Risks

- `wiki_repo.py` and `wiki.py` now coexist with different method names. Wiki routes use `wiki_repo.py`. Agent consolidation pipeline should be wired to `wiki.py`. A future cleanup phase should merge them.
- SQLite unit tests use raw SQL + `SimpleNamespace` adapter — if the ORM layer is changed significantly, tests may need updating to mirror new column names.
