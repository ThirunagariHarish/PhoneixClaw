# Phase 1 Implementation Notes — Agent Knowledge Wiki

**Phase:** 1 — DB Migration + Repository + API  
**Feature:** Agent Knowledge Wiki  
**Date:** 2025-01-01  

---

## What Changed

### Files Created
| File | Purpose |
|------|---------|
| `shared/db/models/wiki.py` | `AgentWikiEntry` + `AgentWikiEntryVersion` SQLAlchemy models |
| `shared/db/migrations/versions/035_agent_wiki.py` | Alembic migration (revision `035_agent_wiki`, down_revision `034_add_analyst_agent`) |
| `apps/api/src/repositories/wiki_repo.py` | `WikiRepository` extending `BaseRepository` |
| `apps/api/src/routes/wiki.py` | 9 API endpoints + Pydantic schemas |
| `tests/unit/test_wiki_models.py` | 18 unit tests for Pydantic schema validation |
| `apps/api/tests/test_wiki_endpoints.py` | 15 endpoint / integration unit tests |

### Files Modified
| File | Change |
|------|--------|
| `shared/db/models/__init__.py` | Added `AgentWikiEntry`, `AgentWikiEntryVersion` import + `__all__` export |
| `apps/api/src/main.py` | Added `wiki_routes` import, `include_router` for `router` + `brain_router`, safety-net `_ensure_prod_schema` entries for both tables |

---

## Architecture Decisions

1. **`VALID_WIKI_CATEGORIES` on the model module** — exported from `shared/db/models/wiki.py` so both the route layer and future service code share the same source of truth.

2. **`/export` and `/query` before `/{entry_id}`** — FastAPI matches routes in registration order; these static-suffix routes must come before the dynamic `{entry_id}` segment to avoid false matches.

3. **`brain_router` with prefix `/api/v2/brain`** — Separate `APIRouter` in the same `wiki.py` file (as specified) to avoid the agents prefix while keeping all wiki logic co-located.

4. **Version snapshot on create** — `create_entry()` writes the initial `AgentWikiEntryVersion` (version=1) atomically alongside the entry, so history is always populated.

5. **Soft-delete pattern** — `DELETE` endpoint sets `is_active=False`; all queries filter `is_active=True`. No hard-delete exposed via the API.

6. **IDOR guard** — `_get_agent_and_verify()` helper checks `agent.user_id == request.state.user_id` OR `request.state.is_admin == True` before any operation. Returns 403 on mismatch.

7. **`query_entries` cross-agent shared entries** — When `include_shared=True`, after collecting the agent's own matches we fill remaining `top_k` slots with `is_shared=True` entries from other agents (Phoenix Brain cross-pollination). This is a keyword-based ilike search; no vector embedding in Phase 1.

---

## Tests Added

### `tests/unit/test_wiki_models.py` (18 tests — all pass)
- Valid category accepted
- All 8 valid categories accepted
- Invalid category raises `ValidationError`
- `confidence_score` 0.0/1.0 bounds
- `confidence_score` <0 / >1 raises `ValidationError`
- `title` min/max length
- `content` min length
- Partial update (WikiEntryUpdate all-optional)
- `change_reason` field
- `is_shared` default false

### `apps/api/tests/test_wiki_endpoints.py` (15 tests — all pass)
- Router prefix checks
- Route path existence / ordering
- `/query` is POST
- Pydantic schema validation (valid + invalid category, partial update, `WikiQueryRequest` defaults + bounds)
- `WikiListResponse` structure
- IDOR raises 403 when non-admin different user
- IDOR allows admin user
- Markdown export rendering

---

## Deviations from Spec

None. All items in the Phase 1 DoD are implemented as specified.

---

## Open Risks

1. **PostgreSQL `ARRAY` type** — `ARRAY(UUID(as_uuid=True))` for `trade_ref_ids` requires PostgreSQL ≥ 9.1. SQLite test harness (if used) will not support this type; all related tests use live DB or are skipped.

2. **`query_entries` is keyword-based, not semantic** — Spec calls this "Semantic-ish search using ilike". True vector/embedding search is deferred to a later phase (when pgvector is available).

3. **No auth on `/api/v2/brain/wiki`** — The `brain_router` endpoint does not call `_get_agent_and_verify` (it has no agent scope). It relies on the global `JWTAuthMiddleware` for authentication. If unauthenticated public access to the brain is needed later, a separate decision is required.
