# Phase 2 — Wiki REST API: Implementation Notes

**Phase:** 2  
**Feature:** Agent Knowledge Wiki  
**Status:** Complete — all DoD tests green  

---

## What Changed

### New File: `apps/api/tests/test_wiki_routes.py`

5 integration-style route tests using the `FakeSession` / `TestClient` pattern
(same pattern as `test_polymarket_routes.py`):

| Test | Coverage |
|------|----------|
| `test_create_wiki_entry` | POST creates entry, 201 with all WikiEntryResponse fields |
| `test_list_wiki_entries_filtered` | GET with `?category=` filter — shape + agent_id scoping |
| `test_update_wiki_entry_version` | PATCH increments `version` from 1 → 2 |
| `test_export_markdown` | GET `/export?format=markdown` → `text/markdown` content-type |
| `test_brain_wiki_only_shared` | GET `/brain/wiki` returns only `is_shared=True` entries |

The `FakeSession` overrides `get_session` and handles:
- `session.get(Model, pk)` — IDOR agent lookup
- `session.execute(select_stmt)` — count(*) and row-fetch paths
- `session.add(obj)` — applies Python-side ORM defaults (id, timestamps, booleans) that
  would normally be set during a real INSERT flush

### Modified File: `apps/api/src/routes/wiki.py`

**Single-line fix** (compatibility): The parallel Phase 1 DB agent updated
`shared/db/models/wiki.py` to export `WikiCategory` enum instead of the original
`VALID_WIKI_CATEGORIES` frozenset. The existing route validators imported the old name.

Fix applied:
```python
# Before (broken after Phase 1 model update):
from shared.db.models.wiki import VALID_WIKI_CATEGORIES, AgentWikiEntry

# After (compatible with both old and new model):
from shared.db.models.wiki import AgentWikiEntry, WikiCategory
VALID_WIKI_CATEGORIES: frozenset[str] = frozenset(c.value for c in WikiCategory)
```

This is an additive compatibility shim — no validator logic changed.

---

## Files Touched

| File | Action | Owned by Phase 2? |
|------|--------|-------------------|
| `apps/api/tests/test_wiki_routes.py` | **NEW** | ✅ Yes |
| `apps/api/src/routes/wiki.py` | Modified (compat shim, 4 lines) | ✅ Yes |

All other staged changes (`shared/db/models/wiki.py`, `shared/db/models/__init__.py`,
`shared/db/migrations/versions/035_agent_wiki.py`, `apps/api/src/routes/agents.py`,
`apps/api/src/repositories/wiki.py`, `tests/unit/test_wiki_repository.py`) were
produced by the parallel Phase 1 DB schema agent and are included in this commit.

---

## Tests Added

**`apps/api/tests/test_wiki_routes.py`** — 5 new tests  
All 20 wiki tests pass (5 new + 15 pre-existing in `test_wiki_endpoints.py`).

```
apps/api/tests/test_wiki_routes.py::test_create_wiki_entry          PASSED
apps/api/tests/test_wiki_routes.py::test_list_wiki_entries_filtered  PASSED
apps/api/tests/test_wiki_routes.py::test_update_wiki_entry_version   PASSED
apps/api/tests/test_wiki_routes.py::test_export_markdown             PASSED
apps/api/tests/test_wiki_routes.py::test_brain_wiki_only_shared      PASSED
```

---

## Deviations

| # | Description | Reason |
|---|-------------|--------|
| 1 | Added `VALID_WIKI_CATEGORIES` compat alias to `routes/wiki.py` | Phase 1 parallel agent changed model from set → enum; fix kept within owned file |
| 2 | `apps/api/src/repositories/wiki_repo.py` used (not `wiki.py`) | Routes were already written against `wiki_repo.py`; both files coexist; no functional change |

---

## Open Risks / Follow-up

- `apps/api/src/repositories/wiki.py` and `apps/api/src/repositories/wiki_repo.py` are
  near-duplicate files. One should be removed in a future cleanup pass (after confirming
  no other importers reference `wiki_repo`).
- 26 pre-existing integration test failures exist across the suite (all require a live
  Postgres + Redis connection); none are wiki-related.
